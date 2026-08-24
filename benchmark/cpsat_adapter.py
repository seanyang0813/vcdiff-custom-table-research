"""Independent integer CP-SAT backend for captured SciPy binary MILPs.

This module deliberately lives outside ``src/vcdiff_opt``.  It does not alter
the frozen optimizer; it translates the optimizer's generated 0/1 model into
OR-Tools CP-SAT, which uses integer coefficients and returns OPTIMAL only after
proving the discrete model optimum.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np
from ortools.sat.python import cp_model


@dataclass(frozen=True)
class CpSatCall:
    variables: int
    original_integer_variables: int
    promoted_binary_variables: int
    constraints: int
    nonzeros: int
    objective: int
    best_bound: int
    branches: int
    conflicts: int
    wall_time_seconds: float
    ortools_version: str
    returned_solution_source: str
    hint_objective: int | None


class BinaryCpSatAdapter:
    """Callable replacement for ``scipy.optimize.milp`` on 0/1 integer models."""

    def __init__(
        self,
        *,
        workers: int = 1,
        max_time_seconds: float | None = None,
        scipy_no_presolve_hint: bool = False,
        log_progress: bool = False,
    ) -> None:
        if workers < 1:
            raise ValueError("workers must be positive")
        self.workers = workers
        self.max_time_seconds = max_time_seconds
        self.scipy_no_presolve_hint = scipy_no_presolve_hint
        self.log_progress = log_progress
        self.calls: list[CpSatCall] = []

    @staticmethod
    def _integers(values: Any, label: str) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        rounded = np.rint(array)
        if not np.allclose(array, rounded, rtol=0.0, atol=1e-9):
            raise ValueError(f"CP-SAT adapter requires integer {label}")
        return rounded.astype(np.int64)

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
        lower_bounds = np.asarray(bounds.lb, dtype=float)
        upper_bounds = np.asarray(bounds.ub, dtype=float)
        if not (
            len(lower_bounds) == variable_count
            and len(upper_bounds) == variable_count
            and np.all(lower_bounds == 0.0)
            and np.all(upper_bounds == 1.0)
        ):
            raise ValueError("CP-SAT adapter requires every variable in [0,1]")
        original_integrality = np.asarray(integrality, dtype=np.uint8)
        if len(original_integrality) != variable_count or np.any(
            (original_integrality != 0) & (original_integrality != 1)
        ):
            raise ValueError("unexpected SciPy integrality vector")

        matrix = constraints.A.tocsr()
        coefficients = self._integers(matrix.data, "constraint coefficients")
        row_lower = np.asarray(constraints.lb, dtype=float)
        row_upper = np.asarray(constraints.ub, dtype=float)
        for values, label in ((row_lower, "row lower bounds"), (row_upper, "row upper bounds")):
            finite = np.isfinite(values)
            self._integers(values[finite], label)

        model = cp_model.CpModel()
        variables = [model.new_bool_var(f"x_{index}") for index in range(variable_count)]
        for row in range(matrix.shape[0]):
            start, end = matrix.indptr[row], matrix.indptr[row + 1]
            columns = matrix.indices[start:end]
            weights = coefficients[start:end]
            expression = cp_model.LinearExpr.weighted_sum(
                [variables[int(column)] for column in columns],
                [int(weight) for weight in weights],
            )
            lower = row_lower[row]
            upper = row_upper[row]
            if np.isfinite(lower) and np.isfinite(upper) and lower == upper:
                model.add(expression == int(round(lower)))
            else:
                if np.isfinite(lower):
                    model.add(expression >= int(round(lower)))
                if np.isfinite(upper):
                    model.add(expression <= int(round(upper)))
        model.minimize(
            cp_model.LinearExpr.weighted_sum(
                variables, [int(value) for value in objective]
            )
        )
        hint_solution: np.ndarray | None = None
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
                hint_solution = np.asarray(hint.x, dtype=float)
                for variable, value in zip(variables, hint.x, strict=True):
                    rounded = int(round(float(value)))
                    if abs(float(value) - rounded) <= 1e-7:
                        model.add_hint(variable, rounded)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = self.workers
        solver.parameters.random_seed = 0
        if self.max_time_seconds is not None:
            solver.parameters.max_time_in_seconds = self.max_time_seconds
        solver.parameters.log_search_progress = self.log_progress or bool(
            (options or {}).get("disp", False)
        )
        status = solver.solve(model)
        if status != cp_model.OPTIMAL:
            return SimpleNamespace(
                success=False,
                status=int(status),
                message=f"CP-SAT status {solver.status_name(status)}",
                x=None,
                fun=None,
            )
        cpsat_solution = np.asarray(
            [solver.value(variable) for variable in variables], dtype=float
        )
        primal = int(round(solver.objective_value))
        dual = int(round(solver.best_objective_bound))
        if primal != dual:
            raise AssertionError(f"CP-SAT OPTIMAL result has unequal bounds: {primal} != {dual}")
        solution = cpsat_solution
        returned_source = "cp_sat"
        hint_objective: int | None = None
        if hint_solution is not None:
            rounded_hint = np.rint(hint_solution)
            integral = np.allclose(
                hint_solution, rounded_hint, rtol=0.0, atol=1e-7
            )
            if integral:
                activity = matrix @ rounded_hint
                lower_ok = np.all(
                    ~np.isfinite(row_lower) | (activity >= row_lower - 1e-9)
                )
                upper_ok = np.all(
                    ~np.isfinite(row_upper) | (activity <= row_upper + 1e-9)
                )
                hint_objective = int(round(float(objective @ rounded_hint)))
                if lower_ok and upper_ok and hint_objective == primal:
                    solution = rounded_hint.astype(float)
                    returned_source = "validated_scipy_no_presolve_hint"
            if returned_source != "validated_scipy_no_presolve_hint":
                raise RuntimeError(
                    "deterministic no-presolve hint did not provide a feasible "
                    "CP-SAT-optimal integer construction"
                )
        import ortools

        self.calls.append(
            CpSatCall(
                variables=variable_count,
                original_integer_variables=int(np.count_nonzero(original_integrality)),
                promoted_binary_variables=int(np.count_nonzero(original_integrality == 0)),
                constraints=matrix.shape[0],
                nonzeros=matrix.nnz,
                objective=primal,
                best_bound=dual,
                branches=int(solver.num_branches),
                conflicts=int(solver.num_conflicts),
                wall_time_seconds=float(solver.wall_time),
                ortools_version=ortools.__version__,
                returned_solution_source=returned_source,
                hint_objective=hint_objective,
            )
        )
        return SimpleNamespace(
            success=True,
            status=0,
            message="OR-Tools CP-SAT proved OPTIMAL",
            x=solution,
            fun=float(primal),
            mip_dual_bound=float(dual),
            mip_gap=0.0,
            mip_node_count=int(solver.num_branches),
        )
