"""Exact lower-bound replay for the strengthened fixed-q selection model.

The floating solvers in this module are candidate generators only.  A call is
accepted solely when:

* occurrence-to-selection rows are added and their summed big-M aggregates
  are removed (an exactly equivalent continuous relaxation),
* the LP row marginals rationalize to a dual that is feasible when replayed
  from integer numerators with integer sparse arithmetic, and
* an integer candidate is exactly feasible and attains that dual bound.

The resulting equality of a verified LP lower bound and a verified integer
upper bound is an exact optimum certificate for the captured binary model.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import numpy as np
from scipy.optimize import LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix, csr_matrix, vstack


FORMAT = "vcdiff-integer-lp-dual-proof-v1"
_INT64_GUARD = 1 << 61


@dataclass(frozen=True)
class IntegerDualCall:
    variables: int
    integer_variables: int
    original_rows: int
    removed_aggregate_rows: int
    activation_rows: int
    equality_rows: int
    inequality_rows: int
    exact_objective: int
    exact_dual_bound: int
    exact_dual_numerator: int
    exact_dual_denominator: int
    lp_reported_objective: float
    lp_elapsed_seconds: float
    candidate_elapsed_seconds: float
    candidate_source: str
    candidate_presolve: bool | None
    model_fingerprint: str
    proof_metadata_path: str | None
    proof_vectors_path: str | None
    proof_vectors_sha256: str | None


@dataclass(frozen=True)
class RationalDualBoundCall:
    variables: int
    original_rows: int
    removed_aggregate_rows: int
    activation_rows: int
    equality_rows: int
    inequality_rows: int
    exact_dual_numerator: int
    exact_dual_denominator: int
    integer_lattice_lower_bound: int
    lp_reported_objective: float
    lp_elapsed_seconds: float
    model_fingerprint: str
    proof_metadata_path: str | None
    proof_vectors_path: str | None
    proof_vectors_sha256: str | None


@dataclass(frozen=True)
class _StandardModel:
    objective: np.ndarray
    integrality: np.ndarray
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    original_matrix: csr_matrix
    original_lower: np.ndarray
    original_upper: np.ndarray
    equality_matrix: csr_matrix
    equality_rhs: np.ndarray
    inequality_matrix: csr_matrix
    inequality_rhs: np.ndarray
    removed_aggregate_rows: tuple[int, ...]
    activation_links: tuple[tuple[int, int], ...]
    fingerprint: str


def _integer_array(values: Any, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        raise ValueError(f"integer-dual adapter requires finite {label}")
    rounded = np.rint(array)
    if not np.allclose(array, rounded, rtol=0.0, atol=1e-9):
        raise ValueError(f"integer-dual adapter requires integer {label}")
    return rounded.astype(np.int64)


def _hash_array(digest: Any, label: str, values: np.ndarray) -> None:
    canonical = np.ascontiguousarray(values)
    digest.update(label.encode("ascii") + b"\0")
    digest.update(np.asarray(canonical.shape, dtype="<i8").tobytes())
    digest.update(canonical.dtype.str.encode("ascii") + b"\0")
    digest.update(canonical.tobytes())


def _hash_sparse(digest: Any, label: str, matrix: csr_matrix) -> None:
    canonical = matrix.tocsr(copy=True)
    canonical.sum_duplicates()
    canonical.sort_indices()
    digest.update(label.encode("ascii") + b"\0")
    digest.update(np.asarray(canonical.shape, dtype="<i8").tobytes())
    _hash_array(digest, f"{label}.indptr", canonical.indptr.astype("<i8"))
    _hash_array(digest, f"{label}.indices", canonical.indices.astype("<i8"))
    _hash_array(digest, f"{label}.data", canonical.data.astype("<i8"))


def _fingerprint(
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    equality_matrix: csr_matrix,
    equality_rhs: np.ndarray,
    inequality_matrix: csr_matrix,
    inequality_rhs: np.ndarray,
) -> str:
    digest = hashlib.sha256()
    digest.update(b"vcdiff-integer-dual-standard-model-v1\0")
    _hash_array(digest, "objective", objective.astype("<i8"))
    _hash_array(digest, "integrality", integrality.astype(np.uint8))
    _hash_array(digest, "lower_bounds", lower_bounds.astype("<i8"))
    _hash_array(digest, "upper_bounds", upper_bounds.astype("<i8"))
    _hash_sparse(digest, "equality_matrix", equality_matrix)
    _hash_array(digest, "equality_rhs", equality_rhs.astype("<i8"))
    _hash_sparse(digest, "inequality_matrix", inequality_matrix)
    _hash_array(digest, "inequality_rhs", inequality_rhs.astype("<i8"))
    return digest.hexdigest()


def _standardize(
    *,
    c: Any,
    integrality: Any,
    bounds: Any,
    constraints: Any,
) -> _StandardModel:
    objective = _integer_array(c, "objective coefficients")
    variable_count = len(objective)
    integer = np.asarray(integrality, dtype=np.uint8)
    if len(integer) != variable_count or np.any((integer != 0) & (integer != 1)):
        raise ValueError("unexpected integrality vector")
    lower_bounds = _integer_array(bounds.lb, "variable lower bounds")
    upper_bounds = _integer_array(bounds.ub, "variable upper bounds")
    if not (
        len(lower_bounds) == variable_count
        and len(upper_bounds) == variable_count
        and np.all(lower_bounds == 0)
        and np.all(upper_bounds == 1)
    ):
        raise ValueError("integer-dual adapter currently requires [0,1] variables")

    original = constraints.A.tocsr(copy=True)
    original.data = _integer_array(original.data, "constraint coefficients")
    original.sum_duplicates()
    original.sort_indices()
    original_lower = np.asarray(constraints.lb, dtype=float)
    original_upper = np.asarray(constraints.ub, dtype=float)
    for values, label in (
        (original_lower, "row lower bounds"),
        (original_upper, "row upper bounds"),
    ):
        finite = np.isfinite(values)
        _integer_array(values[finite], label)

    removed: list[int] = []
    links: list[tuple[int, int]] = []
    for row in range(original.shape[0]):
        if np.isfinite(original_lower[row]) or original_upper[row] != 0.0:
            continue
        start, end = original.indptr[row], original.indptr[row + 1]
        columns = original.indices[start:end]
        coefficients = original.data[start:end]
        negative = np.flatnonzero(coefficients < 0)
        positive = np.flatnonzero(coefficients > 0)
        if (
            len(negative) != 1
            or len(positive) == 0
            or np.any(coefficients[positive] != 1)
        ):
            continue
        selection = int(columns[int(negative[0])])
        if (
            integer[selection] != 1
            or int(coefficients[int(negative[0])]) != -len(positive)
        ):
            continue
        occurrences = tuple(int(columns[int(index)]) for index in positive)
        if any(integer[occurrence] != 0 for occurrence in occurrences):
            continue
        removed.append(row)
        links.extend((occurrence, selection) for occurrence in occurrences)
    if not removed or not links:
        raise ValueError("captured model has no recognized activation aggregates")

    activation = coo_matrix(
        (
            np.tile(np.asarray([1, -1], dtype=np.int64), len(links)),
            (
                np.repeat(np.arange(len(links)), 2),
                np.asarray(links, dtype=np.int64).reshape(-1),
            ),
        ),
        shape=(len(links), variable_count),
        dtype=np.int64,
    ).tocsr()
    retained = np.ones(original.shape[0], dtype=bool)
    retained[removed] = False
    finite_lower = np.isfinite(original_lower)
    finite_upper = np.isfinite(original_upper)
    equality = (
        retained
        & finite_lower
        & finite_upper
        & (original_lower == original_upper)
    )
    upper = retained & finite_upper & ~equality
    lower = retained & finite_lower & ~equality
    equality_matrix = original[equality].astype(np.int64)
    equality_rhs = _integer_array(original_upper[equality], "equality RHS")
    inequality_matrix = vstack(
        (original[upper], -original[lower], activation), format="csr"
    ).astype(np.int64)
    inequality_rhs = np.concatenate(
        (
            _integer_array(original_upper[upper], "upper RHS"),
            -_integer_array(original_lower[lower], "lower RHS"),
            np.zeros(len(links), dtype=np.int64),
        )
    )
    fingerprint = _fingerprint(
        objective,
        integer,
        lower_bounds,
        upper_bounds,
        equality_matrix,
        equality_rhs,
        inequality_matrix,
        inequality_rhs,
    )
    return _StandardModel(
        objective=objective,
        integrality=integer,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        original_matrix=original,
        original_lower=original_lower,
        original_upper=original_upper,
        equality_matrix=equality_matrix,
        equality_rhs=equality_rhs,
        inequality_matrix=inequality_matrix,
        inequality_rhs=inequality_rhs,
        removed_aggregate_rows=tuple(removed),
        activation_links=tuple(links),
        fingerprint=fingerprint,
    )


def _guard_sparse_products(
    model: _StandardModel,
    equality_dual: np.ndarray,
    inequality_dual: np.ndarray,
    denominator: int,
) -> None:
    equality_column_mass = np.asarray(
        abs(model.equality_matrix).sum(axis=0)
    ).reshape(-1)
    inequality_column_mass = np.asarray(
        abs(model.inequality_matrix).sum(axis=0)
    ).reshape(-1)
    equality_max = int(np.max(np.abs(equality_dual), initial=0))
    inequality_max = int(np.max(np.abs(inequality_dual), initial=0))
    # Convert every factor to a Python integer before multiplication.  The
    # guard itself must not be vulnerable to the int64 overflow it is meant
    # to rule out in the sparse matrix-vector products below.
    maximum = (
        int(np.max(equality_column_mass, initial=0)) * equality_max
        + int(np.max(inequality_column_mass, initial=0)) * inequality_max
        + denominator * int(np.max(np.abs(model.objective), initial=0))
    )
    if maximum >= _INT64_GUARD:
        raise OverflowError("dual replay exceeds the guarded int64 product range")


def _dual_numerator(
    model: _StandardModel,
    equality_dual: np.ndarray,
    inequality_dual: np.ndarray,
    denominator: int,
) -> int:
    if denominator <= 0:
        raise ValueError("dual denominator must be positive")
    if equality_dual.shape != model.equality_rhs.shape:
        raise ValueError("equality-dual shape mismatch")
    if inequality_dual.shape != model.inequality_rhs.shape:
        raise ValueError("inequality-dual shape mismatch")
    if np.any(inequality_dual > 0):
        raise ValueError("a <= row has a positive minimization dual multiplier")
    _guard_sparse_products(model, equality_dual, inequality_dual, denominator)
    reduced = (
        denominator * model.objective
        - model.equality_matrix.T @ equality_dual
        - model.inequality_matrix.T @ inequality_dual
    )
    value = sum(
        int(rhs) * int(dual)
        for rhs, dual in zip(model.equality_rhs, equality_dual, strict=True)
    )
    value += sum(
        int(rhs) * int(dual)
        for rhs, dual in zip(model.inequality_rhs, inequality_dual, strict=True)
    )
    value += sum(
        int(coefficient) * int(bound)
        for coefficient, bound in zip(
            reduced,
            np.where(reduced >= 0, model.lower_bounds, model.upper_bounds),
            strict=True,
        )
    )
    return value


def _ceil_fraction(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _candidate_objective(model: _StandardModel, candidate: np.ndarray) -> int:
    if candidate.shape != model.objective.shape:
        raise ValueError("candidate shape mismatch")
    if np.any(candidate < model.lower_bounds) or np.any(candidate > model.upper_bounds):
        raise ValueError("candidate violates variable bounds")
    equality_activity = model.equality_matrix @ candidate
    inequality_activity = model.inequality_matrix @ candidate
    if not np.array_equal(equality_activity, model.equality_rhs):
        raise ValueError("candidate violates an equality row")
    if np.any(inequality_activity > model.inequality_rhs):
        raise ValueError("candidate violates an inequality row")
    original_activity = model.original_matrix @ candidate
    finite_lower = np.isfinite(model.original_lower)
    finite_upper = np.isfinite(model.original_upper)
    if np.any(original_activity[finite_lower] < model.original_lower[finite_lower]):
        raise ValueError("candidate violates an original lower row")
    if np.any(original_activity[finite_upper] > model.original_upper[finite_upper]):
        raise ValueError("candidate violates an original upper row")
    return sum(
        int(coefficient) * int(value)
        for coefficient, value in zip(model.objective, candidate, strict=True)
    )


def _rounded_integer(values: Any, label: str, tolerance: float = 1e-7) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    rounded = np.rint(array)
    if not np.allclose(array, rounded, rtol=0.0, atol=tolerance):
        raise ValueError(f"{label} is not integral within replay tolerance")
    return rounded.astype(np.int64)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_proof(
    directory: Path,
    call_number: int,
    model: _StandardModel,
    equality_dual: np.ndarray,
    inequality_dual: np.ndarray,
    dual_denominator: int,
    dual_numerator: int,
    candidate: np.ndarray,
    objective: int,
) -> tuple[Path, Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"call-{call_number:03d}"
    vectors = directory / f"{stem}.npz"
    np.savez_compressed(
        vectors,
        equality_dual=equality_dual.astype(np.int64),
        inequality_dual=inequality_dual.astype(np.int64),
        candidate=candidate.astype(np.uint8),
    )
    vectors_hash = _sha256(vectors)
    metadata = directory / f"{stem}.json"
    document = {
        "format": FORMAT,
        "model_fingerprint": model.fingerprint,
        "vectors_file": vectors.name,
        "vectors_sha256": vectors_hash,
        "exact_objective": objective,
        "exact_dual_numerator": dual_numerator,
        "exact_dual_denominator": dual_denominator,
        "integer_lattice_lower_bound": _ceil_fraction(
            dual_numerator, dual_denominator
        ),
        "variables": len(model.objective),
        "integer_variables": int(np.count_nonzero(model.integrality)),
        "original_rows": model.original_matrix.shape[0],
        "removed_aggregate_rows": len(model.removed_aggregate_rows),
        "activation_rows": len(model.activation_links),
        "equality_rows": model.equality_matrix.shape[0],
        "inequality_rows": model.inequality_matrix.shape[0],
        "transformation": (
            "replace each sum(x_occ)<=M*y aggregate by all x_occ<=y rows; "
            "the aggregate is their sum, and the rows are integer-redundant"
        ),
        "proof_rule": (
            "ceil of exact rational LP dual lower bound equals exactly feasible "
            "binary witness objective"
        ),
    }
    metadata.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return metadata, vectors, vectors_hash


def _write_bound_proof(
    directory: Path,
    call_number: int,
    model: _StandardModel,
    equality_dual: np.ndarray,
    inequality_dual: np.ndarray,
    dual_denominator: int,
    dual_numerator: int,
) -> tuple[Path, Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"bound-call-{call_number:03d}"
    vectors = directory / f"{stem}.npz"
    np.savez_compressed(
        vectors,
        equality_dual_numerators=equality_dual.astype(np.int64),
        inequality_dual_numerators=inequality_dual.astype(np.int64),
    )
    vectors_hash = _sha256(vectors)
    metadata = directory / f"{stem}.json"
    document = {
        "format": "vcdiff-rational-lp-dual-bound-v1",
        "model_fingerprint": model.fingerprint,
        "vectors_file": vectors.name,
        "vectors_sha256": vectors_hash,
        "exact_dual_numerator": dual_numerator,
        "exact_dual_denominator": dual_denominator,
        "integer_lattice_lower_bound": _ceil_fraction(
            dual_numerator, dual_denominator
        ),
        "variables": len(model.objective),
        "original_rows": model.original_matrix.shape[0],
        "removed_aggregate_rows": len(model.removed_aggregate_rows),
        "activation_rows": len(model.activation_links),
        "equality_rows": model.equality_matrix.shape[0],
        "inequality_rows": model.inequality_matrix.shape[0],
        "transformation": (
            "replace each sum(x_occ)<=M*y aggregate by all x_occ<=y rows; "
            "the aggregate is their sum, and the rows are integer-redundant"
        ),
        "proof_rule": (
            "exact rational LP dual lower bound; its ceiling is valid for the "
            "all-binary parse problem with integer byte objective"
        ),
    }
    metadata.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return metadata, vectors, vectors_hash


def _read_and_verify_proof(
    metadata_path: Path,
    model: _StandardModel,
) -> tuple[np.ndarray, int, Path, str]:
    document = json.loads(metadata_path.read_text())
    if document.get("format") != FORMAT:
        raise ValueError("unexpected integer-dual proof format")
    if document.get("model_fingerprint") != model.fingerprint:
        raise ValueError("integer-dual proof model fingerprint mismatch")
    vectors = metadata_path.parent / document["vectors_file"]
    vectors_hash = _sha256(vectors)
    if vectors_hash != document["vectors_sha256"]:
        raise ValueError("integer-dual proof vector hash mismatch")
    with np.load(vectors, allow_pickle=False) as archive:
        equality_dual = archive["equality_dual"].astype(np.int64)
        inequality_dual = archive["inequality_dual"].astype(np.int64)
        candidate = archive["candidate"].astype(np.int64)
    # v1 integer-only proofs written before rational support are denominator 1.
    denominator = int(document.get("exact_dual_denominator", 1))
    recorded_numerator = int(
        document.get("exact_dual_numerator", document["exact_objective"])
    )
    lower_numerator = _dual_numerator(
        model, equality_dual, inequality_dual, denominator
    )
    upper = _candidate_objective(model, candidate)
    if (
        lower_numerator != recorded_numerator
        or _ceil_fraction(lower_numerator, denominator) != upper
        or upper != int(document["exact_objective"])
    ):
        raise ValueError(
            "integer-dual proof does not close: "
            f"lower={lower_numerator}/{denominator}, upper={upper}"
        )
    return candidate, upper, vectors, vectors_hash


def _read_and_verify_bound_proof(
    metadata_path: Path,
    model: _StandardModel,
) -> tuple[int, int, Path, str]:
    document = json.loads(metadata_path.read_text())
    if document.get("format") != "vcdiff-rational-lp-dual-bound-v1":
        raise ValueError("unexpected rational-dual bound proof format")
    if document.get("model_fingerprint") != model.fingerprint:
        raise ValueError("rational-dual bound model fingerprint mismatch")
    vectors = metadata_path.parent / document["vectors_file"]
    vectors_hash = _sha256(vectors)
    if vectors_hash != document["vectors_sha256"]:
        raise ValueError("rational-dual bound vector hash mismatch")
    with np.load(vectors, allow_pickle=False) as archive:
        equality_dual = archive["equality_dual_numerators"].astype(np.int64)
        inequality_dual = archive["inequality_dual_numerators"].astype(np.int64)
    denominator = int(document["exact_dual_denominator"])
    numerator = _dual_numerator(
        model, equality_dual, inequality_dual, denominator
    )
    if (
        numerator != int(document["exact_dual_numerator"])
        or _ceil_fraction(numerator, denominator)
        != int(document["integer_lattice_lower_bound"])
    ):
        raise ValueError("rational-dual bound proof replay mismatch")
    return numerator, denominator, vectors, vectors_hash


class IntegerDualAdapter:
    """Construct and exactly replay an integer-dual fixed-q certificate."""

    def __init__(
        self,
        *,
        proof_directory: Path | None = None,
        time_limit_seconds: float = 1800.0,
        lp_presolve_attempts: Iterable[bool] = (True, False),
        candidate_presolve_attempts: Iterable[bool] = (True, False),
        bound_only: bool = False,
    ) -> None:
        self.proof_directory = proof_directory
        self.time_limit_seconds = time_limit_seconds
        self.lp_presolve_attempts = tuple(lp_presolve_attempts)
        self.candidate_presolve_attempts = tuple(candidate_presolve_attempts)
        self.bound_only = bound_only
        self.calls: list[IntegerDualCall] = []
        self.bound_calls: list[RationalDualBoundCall] = []

    def __call__(
        self,
        *,
        c: Any,
        integrality: Any,
        bounds: Any,
        constraints: Any,
        options: dict[str, Any] | None = None,
    ) -> Any:
        del options
        model = _standardize(
            c=c,
            integrality=integrality,
            bounds=bounds,
            constraints=constraints,
        )
        lp_result: Any = None
        equality_dual: np.ndarray | None = None
        inequality_dual: np.ndarray | None = None
        exact_lower: int | None = None
        exact_dual_numerator: int | None = None
        exact_dual_denominator: int | None = None
        lp_elapsed = 0.0
        lp_errors: list[str] = []
        for presolve in self.lp_presolve_attempts:
            started = time.monotonic()
            candidate_lp = linprog(
                model.objective.astype(float),
                A_ub=model.inequality_matrix,
                b_ub=model.inequality_rhs,
                A_eq=model.equality_matrix,
                b_eq=model.equality_rhs,
                bounds=list(
                    zip(model.lower_bounds, model.upper_bounds, strict=True)
                ),
                method="highs-ds",
                options={
                    "presolve": presolve,
                    "time_limit": self.time_limit_seconds,
                },
            )
            lp_elapsed += time.monotonic() - started
            if not candidate_lp.success or candidate_lp.x is None:
                lp_errors.append(f"presolve={presolve}: {candidate_lp.message}")
                continue
            rational_candidate: tuple[np.ndarray, np.ndarray, int, int] | None = None
            rational_errors: list[str] = []
            for denominator in (
                1,
                2,
                3,
                4,
                5,
                6,
                8,
                10,
                12,
                16,
                24,
                32,
                48,
                64,
                96,
                128,
                192,
                256,
                384,
                512,
                768,
                1024,
                2048,
                4096,
            ):
                try:
                    scaled_equality = np.asarray(
                        candidate_lp.eqlin.marginals, dtype=float
                    ) * denominator
                    scaled_inequality = np.asarray(
                        candidate_lp.ineqlin.marginals, dtype=float
                    ) * denominator
                    if not (
                        np.all(np.isfinite(scaled_equality))
                        and np.all(np.isfinite(scaled_inequality))
                    ):
                        raise ValueError("nonfinite floating dual proposal")
                    proposed_equality = np.rint(scaled_equality).astype(np.int64)
                    proposed_inequality = np.rint(scaled_inequality).astype(np.int64)
                    proposed_numerator = _dual_numerator(
                        model,
                        proposed_equality,
                        proposed_inequality,
                        denominator,
                    )
                except (ValueError, OverflowError) as error:
                    rational_errors.append(str(error))
                    continue
                proposed = (
                    proposed_equality,
                    proposed_inequality,
                    proposed_numerator,
                    denominator,
                )
                if rational_candidate is None or (
                    proposed_numerator * rational_candidate[3]
                    > rational_candidate[2] * denominator
                ):
                    rational_candidate = proposed
            if rational_candidate is None:
                lp_errors.append(
                    f"presolve={presolve}: no replayable rationalized dual; "
                    + "; ".join(rational_errors[-2:])
                )
                continue
            (
                proposed_equality,
                proposed_inequality,
                proposed_numerator,
                proposed_denominator,
            ) = rational_candidate
            lp_result = candidate_lp
            equality_dual = proposed_equality
            inequality_dual = proposed_inequality
            exact_dual_numerator = proposed_numerator
            exact_dual_denominator = proposed_denominator
            exact_lower = _ceil_fraction(proposed_numerator, proposed_denominator)
            break
        if lp_result is None or equality_dual is None or inequality_dual is None:
            return SimpleNamespace(
                success=False,
                status=4,
                message="no replayable integer LP dual: " + "; ".join(lp_errors),
                x=None,
                fun=None,
            )
        assert exact_lower is not None
        assert exact_dual_numerator is not None
        assert exact_dual_denominator is not None

        bound_metadata: Path | None = None
        bound_vectors: Path | None = None
        bound_vectors_hash: str | None = None
        if self.proof_directory is not None:
            bound_metadata, bound_vectors, bound_vectors_hash = _write_bound_proof(
                self.proof_directory,
                len(self.bound_calls),
                model,
                equality_dual,
                inequality_dual,
                exact_dual_denominator,
                exact_dual_numerator,
            )
            replay_numerator, replay_denominator, _, _ = (
                _read_and_verify_bound_proof(bound_metadata, model)
            )
            if (
                replay_numerator != exact_dual_numerator
                or replay_denominator != exact_dual_denominator
            ):
                raise AssertionError("fresh rational-dual bound failed replay")
        self.bound_calls.append(
            RationalDualBoundCall(
                variables=len(model.objective),
                original_rows=model.original_matrix.shape[0],
                removed_aggregate_rows=len(model.removed_aggregate_rows),
                activation_rows=len(model.activation_links),
                equality_rows=model.equality_matrix.shape[0],
                inequality_rows=model.inequality_matrix.shape[0],
                exact_dual_numerator=exact_dual_numerator,
                exact_dual_denominator=exact_dual_denominator,
                integer_lattice_lower_bound=exact_lower,
                lp_reported_objective=float(lp_result.fun),
                lp_elapsed_seconds=lp_elapsed,
                model_fingerprint=model.fingerprint,
                proof_metadata_path=(
                    None if bound_metadata is None else str(bound_metadata)
                ),
                proof_vectors_path=(
                    None if bound_vectors is None else str(bound_vectors)
                ),
                proof_vectors_sha256=bound_vectors_hash,
            )
        )
        if self.bound_only:
            return SimpleNamespace(
                success=False,
                status="exact_rational_bound_only",
                message=(
                    f"exact rational LP bound {exact_dual_numerator}/"
                    f"{exact_dual_denominator}; integer lattice lower bound "
                    f"{exact_lower}"
                ),
                x=None,
                fun=None,
            )

        candidate: np.ndarray | None = None
        candidate_source = ""
        candidate_presolve: bool | None = None
        candidate_elapsed = 0.0
        try:
            proposed = _rounded_integer(lp_result.x, "LP primal")
            if _candidate_objective(model, proposed) == exact_lower:
                candidate = proposed
                candidate_source = "integral_lp_primal"
        except ValueError:
            pass

        if candidate is None:
            objective_row = csr_matrix(model.objective.reshape(1, -1))
            feasibility_matrix = vstack(
                (model.inequality_matrix, objective_row), format="csr"
            )
            feasibility_rhs = np.concatenate(
                (model.inequality_rhs, np.asarray([exact_lower], dtype=np.int64))
            )
            for presolve in self.candidate_presolve_attempts:
                started = time.monotonic()
                proposal = milp(
                    # The hard objective row makes this a feasibility question,
                    # while the original cost still guides HiGHS toward the
                    # required witness much better than a zero objective.
                    c=model.objective.astype(float),
                    integrality=model.integrality,
                    bounds=bounds,
                    constraints=(
                        LinearConstraint(
                            model.equality_matrix,
                            model.equality_rhs,
                            model.equality_rhs,
                        ),
                        LinearConstraint(
                            feasibility_matrix,
                            -np.inf,
                            feasibility_rhs,
                        ),
                    ),
                    options={
                        "mip_rel_gap": 0.0,
                        "presolve": presolve,
                        "time_limit": self.time_limit_seconds,
                    },
                )
                candidate_elapsed += time.monotonic() - started
                if proposal.x is None:
                    continue
                try:
                    proposed = _rounded_integer(proposal.x, "integer witness")
                    proposed_objective = _candidate_objective(model, proposed)
                except ValueError:
                    continue
                if proposed_objective == exact_lower:
                    candidate = proposed
                    candidate_source = "objective_bound_feasibility_milp"
                    candidate_presolve = presolve
                    break
        if candidate is None:
            return SimpleNamespace(
                success=False,
                status=1,
                message=(
                    "integer LP lower bound was replayed, but no exactly feasible "
                    "binary witness attained it"
                ),
                x=None,
                fun=None,
            )
        exact_upper = _candidate_objective(model, candidate)
        if exact_lower != exact_upper:
            raise AssertionError("verified integer dual and witness do not meet")

        metadata: Path | None = None
        vectors: Path | None = None
        vectors_hash: str | None = None
        if self.proof_directory is not None:
            metadata, vectors, vectors_hash = _write_proof(
                self.proof_directory,
                len(self.calls),
                model,
                equality_dual,
                inequality_dual,
                exact_dual_denominator,
                exact_dual_numerator,
                candidate,
                exact_upper,
            )
            replayed, replayed_objective, _, _ = _read_and_verify_proof(
                metadata, model
            )
            if replayed_objective != exact_upper or not np.array_equal(
                replayed, candidate
            ):
                raise AssertionError("freshly written proof failed independent replay")

        call = IntegerDualCall(
            variables=len(model.objective),
            integer_variables=int(np.count_nonzero(model.integrality)),
            original_rows=model.original_matrix.shape[0],
            removed_aggregate_rows=len(model.removed_aggregate_rows),
            activation_rows=len(model.activation_links),
            equality_rows=model.equality_matrix.shape[0],
            inequality_rows=model.inequality_matrix.shape[0],
            exact_objective=exact_upper,
            exact_dual_bound=exact_lower,
            exact_dual_numerator=exact_dual_numerator,
            exact_dual_denominator=exact_dual_denominator,
            lp_reported_objective=float(lp_result.fun),
            lp_elapsed_seconds=lp_elapsed,
            candidate_elapsed_seconds=candidate_elapsed,
            candidate_source=candidate_source,
            candidate_presolve=candidate_presolve,
            model_fingerprint=model.fingerprint,
            proof_metadata_path=None if metadata is None else str(metadata),
            proof_vectors_path=None if vectors is None else str(vectors),
            proof_vectors_sha256=vectors_hash,
        )
        self.calls.append(call)
        return SimpleNamespace(
            success=True,
            status=0,
            message=(
                "ceiling of exact rational LP dual lower bound equals exactly "
                "feasible binary witness"
            ),
            x=candidate.astype(float),
            fun=float(exact_upper),
            mip_dual_bound=float(exact_lower),
            mip_gap=0.0,
            mip_node_count=0,
        )


class IntegerDualReplayAdapter:
    """Replay stored vectors against a freshly regenerated captured model."""

    def __init__(self, proof_directory: Path) -> None:
        self.proof_directory = proof_directory
        self.calls: list[IntegerDualCall] = []

    def __call__(
        self,
        *,
        c: Any,
        integrality: Any,
        bounds: Any,
        constraints: Any,
        options: dict[str, Any] | None = None,
    ) -> Any:
        del options
        model = _standardize(
            c=c,
            integrality=integrality,
            bounds=bounds,
            constraints=constraints,
        )
        metadata = self.proof_directory / f"call-{len(self.calls):03d}.json"
        candidate, objective, vectors, vectors_hash = _read_and_verify_proof(
            metadata, model
        )
        document = json.loads(metadata.read_text())
        self.calls.append(
            IntegerDualCall(
                variables=len(model.objective),
                integer_variables=int(np.count_nonzero(model.integrality)),
                original_rows=model.original_matrix.shape[0],
                removed_aggregate_rows=len(model.removed_aggregate_rows),
                activation_rows=len(model.activation_links),
                equality_rows=model.equality_matrix.shape[0],
                inequality_rows=model.inequality_matrix.shape[0],
                exact_objective=objective,
                exact_dual_bound=objective,
                exact_dual_numerator=int(
                    document.get("exact_dual_numerator", document["exact_objective"])
                ),
                exact_dual_denominator=int(
                    document.get("exact_dual_denominator", 1)
                ),
                lp_reported_objective=float("nan"),
                lp_elapsed_seconds=0.0,
                candidate_elapsed_seconds=0.0,
                candidate_source="stored_integer_dual_replay",
                candidate_presolve=None,
                model_fingerprint=model.fingerprint,
                proof_metadata_path=str(metadata),
                proof_vectors_path=str(vectors),
                proof_vectors_sha256=vectors_hash,
            )
        )
        return SimpleNamespace(
            success=True,
            status=0,
            message=document["proof_rule"],
            x=candidate.astype(float),
            fun=float(objective),
            mip_dual_bound=float(objective),
            mip_gap=0.0,
            mip_node_count=0,
        )


class RationalDualBoundReplayAdapter:
    """Replay a stored rational LP lower bound without constructing a witness."""

    def __init__(self, proof_directory: Path) -> None:
        self.proof_directory = proof_directory
        self.calls: list[RationalDualBoundCall] = []

    def __call__(
        self,
        *,
        c: Any,
        integrality: Any,
        bounds: Any,
        constraints: Any,
        options: dict[str, Any] | None = None,
    ) -> Any:
        del options
        model = _standardize(
            c=c,
            integrality=integrality,
            bounds=bounds,
            constraints=constraints,
        )
        metadata = (
            self.proof_directory / f"bound-call-{len(self.calls):03d}.json"
        )
        numerator, denominator, vectors, vectors_hash = (
            _read_and_verify_bound_proof(metadata, model)
        )
        document = json.loads(metadata.read_text())
        self.calls.append(
            RationalDualBoundCall(
                variables=len(model.objective),
                original_rows=model.original_matrix.shape[0],
                removed_aggregate_rows=len(model.removed_aggregate_rows),
                activation_rows=len(model.activation_links),
                equality_rows=model.equality_matrix.shape[0],
                inequality_rows=model.inequality_matrix.shape[0],
                exact_dual_numerator=numerator,
                exact_dual_denominator=denominator,
                integer_lattice_lower_bound=_ceil_fraction(
                    numerator, denominator
                ),
                lp_reported_objective=float("nan"),
                lp_elapsed_seconds=0.0,
                model_fingerprint=model.fingerprint,
                proof_metadata_path=str(metadata),
                proof_vectors_path=str(vectors),
                proof_vectors_sha256=vectors_hash,
            )
        )
        return SimpleNamespace(
            success=False,
            status="replayed_exact_rational_bound_only",
            message=document["proof_rule"],
            x=None,
            fun=None,
        )


def calls_as_dicts(calls: Iterable[IntegerDualCall]) -> list[dict[str, Any]]:
    return [asdict(call) for call in calls]


def bound_calls_as_dicts(
    calls: Iterable[RationalDualBoundCall],
) -> list[dict[str, Any]]:
    return [asdict(call) for call in calls]
