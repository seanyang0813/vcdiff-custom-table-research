"""Numerically exact SCIP backend for the frozen SciPy mixed-integer model.

The adapter preserves the optimizer's original integrality vector: path-flow
variables remain continuous and table/q/varint-state variables remain binary.
It serializes the captured integer-coefficient model as MPS, enables SCIP 10's
exact solving mode before reading the problem, and accepts only an optimal
solution with an equal integral primal and rationally safe dual bound.
"""

from __future__ import annotations

import gc
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from pyscipopt import Model


@dataclass(frozen=True)
class ScipExactCall:
    variables: int
    integer_variables: int
    continuous_variables: int
    original_constraints: int
    expanded_constraints: int
    nonzeros: int
    expanded_nonzeros: int
    activation_link_constraints: int
    objective: int
    best_bound: int
    nodes: int
    scip_version: str
    exact_mode: bool
    returned_solution_source: str
    hint_objective: int | None
    mps_sha256: str
    time_limit_seconds: float
    memory_limit_mb: float
    threads: int
    random_seed_shift: int
    permutation_seed: int
    lp_seed: int


class ScipExactAdapter:
    """Callable replacement for ``scipy.optimize.milp`` using exact SCIP."""

    def __init__(
        self,
        *,
        scipy_no_presolve_hint: bool = True,
        temporary_parent: Path | None = None,
        display: bool = False,
        promote_all_binary: bool = False,
        strengthen_activation_links: bool = False,
        time_limit_seconds: float = 7200.0,
        memory_limit_mb: float = 6000.0,
    ) -> None:
        self.scipy_no_presolve_hint = scipy_no_presolve_hint
        self.temporary_parent = temporary_parent
        self.display = display
        self.promote_all_binary = promote_all_binary
        self.strengthen_activation_links = strengthen_activation_links
        self.time_limit_seconds = time_limit_seconds
        self.memory_limit_mb = memory_limit_mb
        self.calls: list[ScipExactCall] = []

    @staticmethod
    def _integers(values: Any, label: str) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        rounded = np.rint(array)
        if not np.allclose(array, rounded, rtol=0.0, atol=1e-9):
            raise ValueError(f"exact SCIP adapter requires integer {label}")
        return rounded.astype(np.int64)

    @staticmethod
    def _write_mps(
        path: Path,
        objective: np.ndarray,
        integrality: np.ndarray,
        matrix: Any,
        row_lower: np.ndarray,
        row_upper: np.ndarray,
        activation_links: list[tuple[int, int]],
    ) -> tuple[int, int]:
        expanded: list[list[tuple[str, int]]] = []
        expanded_count = 0
        for row, (lower, upper) in enumerate(
            zip(row_lower, row_upper, strict=True)
        ):
            descriptors: list[tuple[str, int]] = []
            if np.isfinite(lower) and np.isfinite(upper) and lower == upper:
                descriptors.append((f"E{row}", int(round(lower))))
            else:
                if np.isfinite(lower):
                    descriptors.append((f"G{row}", int(round(lower))))
                if np.isfinite(upper):
                    descriptors.append((f"L{row}", int(round(upper))))
            if not descriptors:
                raise ValueError(f"constraint row {row} has no finite side")
            expanded.append(descriptors)
            expanded_count += len(descriptors)

        csc = matrix.tocsc()
        expanded_nonzeros = 0
        with path.open("w", buffering=1024 * 1024) as handle:
            handle.write("NAME VCDIFF_EXACT\nROWS\n N OBJ\n")
            for row, descriptors in enumerate(expanded):
                lower, upper = row_lower[row], row_upper[row]
                if np.isfinite(lower) and np.isfinite(upper) and lower == upper:
                    handle.write(f" E {descriptors[0][0]}\n")
                else:
                    for name, _ in descriptors:
                        handle.write(f" {'G' if name[0] == 'G' else 'L'} {name}\n")
            for link in range(len(activation_links)):
                handle.write(f" L K{link}\n")
            handle.write("COLUMNS\n")
            links_by_column: dict[int, list[tuple[int, int]]] = {}
            for link, (occurrence, selection) in enumerate(activation_links):
                links_by_column.setdefault(occurrence, []).append((link, 1))
                links_by_column.setdefault(selection, []).append((link, -1))
            integer_section = False
            marker = 0
            for column in range(len(objective)):
                is_integer = bool(integrality[column])
                if is_integer != integer_section:
                    keyword = "INTORG" if is_integer else "INTEND"
                    handle.write(
                        f" M{marker} 'MARKER' '{keyword}'\n"
                    )
                    marker += 1
                    integer_section = is_integer
                name = f"X{column}"
                coefficient = int(objective[column])
                if coefficient:
                    handle.write(f" {name} OBJ {coefficient}\n")
                start, end = csc.indptr[column], csc.indptr[column + 1]
                for offset in range(start, end):
                    row = int(csc.indices[offset])
                    value = int(round(float(csc.data[offset])))
                    if value == 0:
                        continue
                    for row_name, _ in expanded[row]:
                        handle.write(f" {name} {row_name} {value}\n")
                        expanded_nonzeros += 1
                for link, value in links_by_column.get(column, []):
                    handle.write(f" {name} K{link} {value}\n")
                    expanded_nonzeros += 1
            if integer_section:
                handle.write(f" M{marker} 'MARKER' 'INTEND'\n")
            handle.write("RHS\n")
            for descriptors in expanded:
                for name, right_hand_side in descriptors:
                    handle.write(f" RHS1 {name} {right_hand_side}\n")
            for link in range(len(activation_links)):
                handle.write(f" RHS1 K{link} 0\n")
            handle.write("BOUNDS\n")
            for column, is_integer in enumerate(integrality):
                name = f"X{column}"
                if is_integer:
                    handle.write(f" BV BND {name}\n")
                else:
                    handle.write(f" LO BND {name} 0\n")
                    handle.write(f" UP BND {name} 1\n")
            handle.write("ENDATA\n")
        return expanded_count + len(activation_links), expanded_nonzeros

    @staticmethod
    def _activation_links(
        matrix: Any,
        row_lower: np.ndarray,
        row_upper: np.ndarray,
        integrality: np.ndarray,
    ) -> list[tuple[int, int]]:
        """Recover exact occurrence-to-pattern implications from big-M rows."""
        links: list[tuple[int, int]] = []
        csr = matrix.tocsr()
        for row in range(csr.shape[0]):
            if np.isfinite(row_lower[row]) or row_upper[row] != 0.0:
                continue
            start, end = csr.indptr[row], csr.indptr[row + 1]
            columns = csr.indices[start:end]
            values = np.rint(csr.data[start:end]).astype(np.int64)
            negative = np.flatnonzero(values < 0)
            positive = np.flatnonzero(values > 0)
            if (
                len(negative) != 1
                or len(positive) == 0
                or np.any(values[positive] != 1)
            ):
                continue
            selection = int(columns[int(negative[0])])
            if (
                integrality[selection] != 1
                or int(values[int(negative[0])]) != -len(positive)
            ):
                continue
            occurrences = [int(columns[int(index)]) for index in positive]
            if any(integrality[occurrence] != 0 for occurrence in occurrences):
                continue
            links.extend((occurrence, selection) for occurrence in occurrences)
        return links

    def __call__(
        self,
        *,
        c: Any,
        integrality: Any,
        bounds: Any,
        constraints: Any,
        options: dict[str, Any] | None = None,
    ) -> Any:
        objective = self._integers(c, "objective coefficients")
        variable_count = len(objective)
        integrality_array = np.asarray(integrality, dtype=np.uint8)
        if len(integrality_array) != variable_count or np.any(
            (integrality_array != 0) & (integrality_array != 1)
        ):
            raise ValueError("unexpected SciPy integrality vector")
        exact_integrality = (
            np.ones(variable_count, dtype=np.uint8)
            if self.promote_all_binary
            else integrality_array
        )
        lower_bounds = np.asarray(bounds.lb, dtype=float)
        upper_bounds = np.asarray(bounds.ub, dtype=float)
        if not (
            len(lower_bounds) == variable_count
            and len(upper_bounds) == variable_count
            and np.all(lower_bounds == 0.0)
            and np.all(upper_bounds == 1.0)
        ):
            raise ValueError("exact SCIP adapter requires every variable in [0,1]")

        matrix = constraints.A.tocsr()
        self._integers(matrix.data, "constraint coefficients")
        row_lower = np.asarray(constraints.lb, dtype=float)
        row_upper = np.asarray(constraints.ub, dtype=float)
        for values, label in (
            (row_lower, "row lower bounds"),
            (row_upper, "row upper bounds"),
        ):
            finite = np.isfinite(values)
            self._integers(values[finite], label)
        activation_links = (
            self._activation_links(
                matrix,
                row_lower,
                row_upper,
                integrality_array,
            )
            if self.strengthen_activation_links
            else []
        )

        hint_solution: np.ndarray | None = None
        validated_hint: np.ndarray | None = None
        hint_objective: int | None = None
        if self.scipy_no_presolve_hint:
            from scipy.optimize import milp as scipy_milp

            hint = scipy_milp(
                c=np.asarray(c),
                integrality=np.asarray(integrality),
                bounds=bounds,
                constraints=constraints,
                options={"mip_rel_gap": 0.0, "presolve": False},
            )
            if hint.success and hint.x is not None:
                hint_solution = np.asarray(hint.x, dtype=float).copy()
            del hint
            gc.collect()
            if hint_solution is None:
                raise RuntimeError("no-presolve SciPy did not produce a candidate hint")
            rounded_hint = np.rint(hint_solution)
            if not np.allclose(
                hint_solution, rounded_hint, rtol=0.0, atol=1e-7
            ):
                raise RuntimeError("no-presolve candidate hint is not integral")
            activity = matrix @ rounded_hint
            lower_ok = np.all(
                ~np.isfinite(row_lower) | (activity >= row_lower - 1e-9)
            )
            upper_ok = np.all(
                ~np.isfinite(row_upper) | (activity <= row_upper + 1e-9)
            )
            if not lower_ok or not upper_ok:
                raise RuntimeError("no-presolve candidate hint violates captured matrix")
            validated_hint = rounded_hint.astype(float)
            hint_objective = int(round(float(objective @ rounded_hint)))

        parent = self.temporary_parent
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="vcdiff-scip-exact-",
            dir=None if parent is None else str(parent),
        ) as directory:
            mps_path = Path(directory) / "model.mps"
            expanded_constraints, expanded_nonzeros = self._write_mps(
                mps_path,
                objective,
                exact_integrality,
                matrix,
                row_lower,
                row_upper,
                activation_links,
            )
            mps_sha256 = hashlib.sha256(mps_path.read_bytes()).hexdigest()
            model = Model()
            model.freeProb()
            model.enableExactSolving(True)
            if not self.display and not bool((options or {}).get("disp", False)):
                model.hideOutput()
            model.readProblem(str(mps_path))
            if model.getParam("exact/enable") is not True:
                raise RuntimeError("SCIP exact solving mode is not active")
            # Freeze a single-threaded deterministic execution and explicit
            # fail-visible resource limits.  A limit status is never accepted
            # as an exact label by this adapter.
            model.setParam("parallel/maxnthreads", 1)
            model.setParam("lp/threads", 1)
            model.setParam("randomization/randomseedshift", 0)
            model.setParam("randomization/permutationseed", 0)
            model.setParam("randomization/lpseed", 0)
            model.setParam("randomization/permuteconss", False)
            model.setParam("randomization/permutevars", False)
            model.setParam("limits/time", self.time_limit_seconds)
            model.setParam("limits/memory", self.memory_limit_mb)
            original_variables = model.getVars(transformed=False)
            if validated_hint is not None:
                incumbent = model.createOrigSol()
                for variable in original_variables:
                    name = variable.name
                    if not name.startswith("X"):
                        raise ValueError(f"unexpected MPS variable name {name}")
                    model.setSolVal(
                        incumbent,
                        variable,
                        float(validated_hint[int(name[1:])]),
                    )
                if not model.addSol(incumbent, free=True):
                    raise RuntimeError("exact SCIP rejected the validated incumbent")
            model.optimize()
            status = str(model.getStatus())
            if status != "optimal":
                return SimpleNamespace(
                    success=False,
                    status=status,
                    message=f"exact SCIP status {status}",
                    x=None,
                    fun=None,
                )
            primal_float = float(model.getObjVal())
            dual_float = float(model.getDualbound())
            primal = int(round(primal_float))
            dual = int(round(dual_float))
            if (
                abs(primal_float - primal) > 1e-7
                or abs(dual_float - dual) > 1e-7
                or primal != dual
            ):
                raise RuntimeError(
                    f"exact SCIP returned unequal/nonintegral bounds: "
                    f"{primal_float} != {dual_float}"
                )
            exact_solution = np.zeros(variable_count, dtype=float)
            for variable in original_variables:
                name = variable.name
                if not name.startswith("X"):
                    raise ValueError(f"unexpected MPS variable name {name}")
                exact_solution[int(name[1:])] = float(model.getVal(variable))
            nodes = int(model.getNNodes())
            scip_version = (
                f"{model.getMajorVersion()}.{model.getMinorVersion()}."
                f"{model.getTechVersion()}"
            )

        solution = exact_solution
        returned_source = "exact_scip"
        if validated_hint is not None:
            if hint_objective == primal:
                solution = validated_hint
                returned_source = "validated_scipy_no_presolve_hint"
            else:
                raise RuntimeError(
                    "deterministic no-presolve hint did not provide a feasible "
                    "exact-SCIP-optimal integral construction"
                )

        self.calls.append(
            ScipExactCall(
                variables=variable_count,
                integer_variables=int(np.count_nonzero(exact_integrality)),
                continuous_variables=int(np.count_nonzero(exact_integrality == 0)),
                original_constraints=matrix.shape[0],
                expanded_constraints=expanded_constraints,
                nonzeros=matrix.nnz,
                expanded_nonzeros=expanded_nonzeros,
                activation_link_constraints=len(activation_links),
                objective=primal,
                best_bound=dual,
                nodes=nodes,
                scip_version=scip_version,
                exact_mode=True,
                returned_solution_source=returned_source,
                hint_objective=hint_objective,
                mps_sha256=mps_sha256,
                time_limit_seconds=self.time_limit_seconds,
                memory_limit_mb=self.memory_limit_mb,
                threads=1,
                random_seed_shift=0,
                permutation_seed=0,
                lp_seed=0,
            )
        )
        return SimpleNamespace(
            success=True,
            status=0,
            message="SCIP numerically exact mode proved OPTIMAL",
            x=solution,
            fun=float(primal),
            mip_dual_bound=float(dual),
            mip_gap=0.0,
            mip_node_count=nodes,
        )
