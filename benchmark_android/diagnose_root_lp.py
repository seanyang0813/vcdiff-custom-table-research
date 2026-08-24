#!/usr/bin/env python3
"""Measure the strengthened fixed-q root LP without assigning an exact label.

This diagnostic captures the frozen optimizer's fixed-q model, adds the same
integer-redundant occurrence-to-selection rows used by the exact-SCIP
amendment, and solves only its continuous relaxation.  A floating-point LP
result is scouting evidence, never an exact certificate.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NoReturn

import numpy as np
from scipy.optimize import LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix, vstack

import vcdiff_opt.optimizer as optimizer
from benchmark.scip_exact_adapter import ScipExactAdapter
from vcdiff_opt.codec import build_custom_table, encode_file, encode_file_header
from vcdiff_opt.model import ADD, Atom, Pattern, WindowTrace


ROOT = Path(__file__).resolve().parent.parent


class ModelCaptured(RuntimeError):
    """Stop ``solve_selection`` after its model has been inspected."""


@dataclass(frozen=True)
class LpDiagnostic:
    physical_slots: int
    variables: int
    path_variables: int
    selection_variables: int
    original_rows: int
    removed_redundant_aggregate_rows: int
    activation_rows: int
    equality_rows: int
    inequality_rows: int
    status: int
    success: bool
    message: str
    elapsed_seconds: float
    objective: float | None
    objective_nearest_integer: int | None
    objective_integer_distance: float | None
    fractional_path_variables: int | None
    fractional_selection_variables: int | None
    maximum_variable_fractionality: float | None
    floating_dual_objective: float | None
    floating_primal_dual_gap: float | None
    maximum_stationarity_residual: float | None
    nonintegral_dual_marginals: int | None
    maximum_dual_marginal_integer_distance: float | None
    common_denominator_trials: list[dict[str, int | float | bool]] | None
    mip_candidate_attempted: bool
    mip_candidate_status: int | None
    mip_candidate_message: str | None
    mip_candidate_elapsed_seconds: float | None
    mip_candidate_objective: int | None
    mip_candidate_exactly_feasible: bool | None
    mip_candidate_attains_integer_dual: bool | None


def _continuous_relaxation(
    *,
    physical_slots: int,
    c: Any,
    integrality: Any,
    bounds: Any,
    constraints: Any,
    time_limit_seconds: float,
    options: dict[str, Any] | None = None,
    solve_mip_candidate: bool = False,
    lp_presolve: bool = False,
    mip_presolve: bool = False,
) -> LpDiagnostic:
    del options
    objective = np.asarray(c, dtype=float)
    integer = np.asarray(integrality, dtype=np.uint8)
    matrix = constraints.A.tocsr()
    row_lower = np.asarray(constraints.lb, dtype=float)
    row_upper = np.asarray(constraints.ub, dtype=float)
    variable_count = len(objective)
    path_count = int(np.flatnonzero(integer)[0])

    activation_links: list[tuple[int, int]] = []
    redundant_aggregate_rows: list[int] = []
    csr = matrix.tocsr()
    for row in range(csr.shape[0]):
        if np.isfinite(row_lower[row]) or row_upper[row] != 0.0:
            continue
        start, end = csr.indptr[row], csr.indptr[row + 1]
        columns = csr.indices[start:end]
        coefficients = np.rint(csr.data[start:end]).astype(np.int64)
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
        occurrences = [int(columns[int(index)]) for index in positive]
        if any(integer[occurrence] != 0 for occurrence in occurrences):
            continue
        redundant_aggregate_rows.append(row)
        activation_links.extend((occurrence, selection) for occurrence in occurrences)
    if activation_links != ScipExactAdapter._activation_links(
        matrix, row_lower, row_upper, integer
    ):
        raise AssertionError("activation-row reconstruction drift")
    activation_matrix = coo_matrix(
        (
            np.tile(np.asarray([1.0, -1.0]), len(activation_links)),
            (
                np.repeat(np.arange(len(activation_links)), 2),
                np.asarray(activation_links, dtype=np.int64).reshape(-1),
            ),
        ),
        shape=(len(activation_links), variable_count),
    ).tocsr()

    finite_lower = np.isfinite(row_lower)
    finite_upper = np.isfinite(row_upper)
    retained = np.ones(len(row_lower), dtype=bool)
    retained[redundant_aggregate_rows] = False
    equality = retained & finite_lower & finite_upper & (row_lower == row_upper)
    upper = retained & finite_upper & ~equality
    lower = retained & finite_lower & ~equality

    a_eq = matrix[equality]
    b_eq = row_upper[equality]
    inequality_parts = [matrix[upper], -matrix[lower], activation_matrix]
    rhs_parts = [
        row_upper[upper],
        -row_lower[lower],
        np.zeros(len(activation_links), dtype=float),
    ]
    a_ub = vstack(inequality_parts, format="csr")
    b_ub = np.concatenate(rhs_parts)

    started = time.monotonic()
    result = linprog(
        objective,
        A_ub=a_ub,
        b_ub=b_ub,
        A_eq=a_eq,
        b_eq=b_eq,
        bounds=list(zip(bounds.lb, bounds.ub, strict=True)),
        method="highs-ds",
        options={"presolve": lp_presolve, "time_limit": time_limit_seconds},
    )
    elapsed = time.monotonic() - started

    common = {
        "physical_slots": physical_slots,
        "variables": variable_count,
        "path_variables": path_count,
        "selection_variables": variable_count - path_count,
        "original_rows": matrix.shape[0],
        "removed_redundant_aggregate_rows": len(redundant_aggregate_rows),
        "activation_rows": len(activation_links),
        "equality_rows": a_eq.shape[0],
        "inequality_rows": a_ub.shape[0],
        "status": int(result.status),
        "success": bool(result.success),
        "message": str(result.message),
        "elapsed_seconds": elapsed,
    }
    if not result.success or result.x is None or result.fun is None:
        return LpDiagnostic(
            **common,
            objective=None,
            objective_nearest_integer=None,
            objective_integer_distance=None,
            fractional_path_variables=None,
            fractional_selection_variables=None,
            maximum_variable_fractionality=None,
            floating_dual_objective=None,
            floating_primal_dual_gap=None,
            maximum_stationarity_residual=None,
            nonintegral_dual_marginals=None,
            maximum_dual_marginal_integer_distance=None,
            common_denominator_trials=None,
            mip_candidate_attempted=False,
            mip_candidate_status=None,
            mip_candidate_message=None,
            mip_candidate_elapsed_seconds=None,
            mip_candidate_objective=None,
            mip_candidate_exactly_feasible=None,
            mip_candidate_attains_integer_dual=None,
        )

    solution = np.asarray(result.x)
    fractionality = np.abs(solution - np.rint(solution))
    equality_marginals = np.asarray(result.eqlin.marginals)
    inequality_marginals = np.asarray(result.ineqlin.marginals)
    lower_marginals = np.asarray(result.lower.marginals)
    upper_marginals = np.asarray(result.upper.marginals)
    dual_objective = float(
        b_eq @ equality_marginals
        + b_ub @ inequality_marginals
        + np.asarray(bounds.lb) @ lower_marginals
        + np.asarray(bounds.ub) @ upper_marginals
    )
    stationarity = (
        objective
        - a_eq.T @ equality_marginals
        - a_ub.T @ inequality_marginals
        - lower_marginals
        - upper_marginals
    )
    all_marginals = np.concatenate(
        (
            equality_marginals,
            inequality_marginals,
            lower_marginals,
            upper_marginals,
        )
    )
    marginal_distance = np.abs(all_marginals - np.rint(all_marginals))
    nearest = int(round(float(result.fun)))
    integer_a_eq = a_eq.astype(np.int64)
    integer_a_ub = a_ub.astype(np.int64)
    integer_b_eq = np.rint(b_eq).astype(np.int64)
    integer_b_ub = np.rint(b_ub).astype(np.int64)
    integer_objective = np.rint(objective).astype(np.int64)
    denominator_trials: list[dict[str, int | float | bool]] = []
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
        equality_numerators = np.rint(
            equality_marginals * denominator
        ).astype(np.int64)
        inequality_numerators = np.rint(
            inequality_marginals * denominator
        ).astype(np.int64)
        reduced_cost_numerators = (
            denominator * integer_objective
            - integer_a_eq.T @ equality_numerators
            - integer_a_ub.T @ inequality_numerators
        )
        dual_numerator = int(
            integer_b_eq @ equality_numerators
            + integer_b_ub @ inequality_numerators
            + np.minimum(reduced_cost_numerators, 0).sum(dtype=np.int64)
        )
        target_numerator = nearest * denominator
        rounding_error = max(
            float(
                np.max(
                    np.abs(
                        equality_marginals * denominator
                        - equality_numerators
                    )
                )
            ),
            float(
                np.max(
                    np.abs(
                        inequality_marginals * denominator
                        - inequality_numerators
                    )
                )
            ),
        )
        sign_feasible = bool(np.all(inequality_numerators <= 0))
        denominator_trials.append(
            {
                "denominator": denominator,
                "dual_numerator": dual_numerator,
                "target_numerator": target_numerator,
                "deficit_numerator": target_numerator - dual_numerator,
                "inequality_sign_feasible": sign_feasible,
                "maximum_scaled_rounding_error": rounding_error,
                "exact_target_attained": sign_feasible
                and dual_numerator == target_numerator,
            }
        )
    mip_status: int | None = None
    mip_message: str | None = None
    mip_elapsed: float | None = None
    mip_objective: int | None = None
    mip_exactly_feasible: bool | None = None
    mip_attains_dual: bool | None = None
    if solve_mip_candidate:
        mip_started = time.monotonic()
        exact_dual_bound = int(denominator_trials[0]["dual_numerator"])
        candidate_a_ub = vstack(
            (a_ub, coo_matrix(integer_objective.reshape(1, -1))),
            format="csr",
        )
        candidate_b_ub = np.concatenate(
            (b_ub, np.asarray([exact_dual_bound], dtype=float))
        )
        mip_result = milp(
            c=np.zeros_like(objective),
            integrality=integer,
            bounds=bounds,
            constraints=(
                LinearConstraint(a_eq, b_eq, b_eq),
                LinearConstraint(candidate_a_ub, -np.inf, candidate_b_ub),
            ),
            options={
                "mip_rel_gap": 0.0,
                "presolve": mip_presolve,
                "time_limit": time_limit_seconds,
            },
        )
        mip_elapsed = time.monotonic() - mip_started
        mip_status = int(mip_result.status)
        mip_message = str(mip_result.message)
        mip_exactly_feasible = False
        if mip_result.x is not None:
            candidate = np.rint(np.asarray(mip_result.x)).astype(np.int64)
            integral = bool(
                np.allclose(mip_result.x, candidate, rtol=0.0, atol=1e-7)
            )
            exact_bounds = bool(
                np.all(candidate >= np.asarray(bounds.lb, dtype=np.int64))
                and np.all(candidate <= np.asarray(bounds.ub, dtype=np.int64))
            )
            exact_equalities = bool(
                np.array_equal(integer_a_eq @ candidate, integer_b_eq)
            )
            exact_inequalities = bool(
                np.all(integer_a_ub @ candidate <= integer_b_ub)
            )
            mip_exactly_feasible = (
                integral and exact_bounds and exact_equalities and exact_inequalities
            )
            if mip_exactly_feasible:
                mip_objective = int(integer_objective @ candidate)
        denominator_one = denominator_trials[0]
        if mip_objective is not None:
            mip_attains_dual = bool(
                denominator_one["exact_target_attained"]
                and mip_objective == denominator_one["dual_numerator"]
            )
    return LpDiagnostic(
        **common,
        objective=float(result.fun),
        objective_nearest_integer=nearest,
        objective_integer_distance=abs(float(result.fun) - nearest),
        fractional_path_variables=int(np.count_nonzero(fractionality[:path_count] > 1e-7)),
        fractional_selection_variables=int(
            np.count_nonzero(fractionality[path_count:] > 1e-7)
        ),
        maximum_variable_fractionality=float(np.max(fractionality)),
        floating_dual_objective=dual_objective,
        floating_primal_dual_gap=float(result.fun) - dual_objective,
        maximum_stationarity_residual=float(np.max(np.abs(stationarity))),
        nonintegral_dual_marginals=int(np.count_nonzero(marginal_distance > 1e-7)),
        maximum_dual_marginal_integer_distance=float(np.max(marginal_distance)),
        common_denominator_trials=denominator_trials,
        mip_candidate_attempted=solve_mip_candidate,
        mip_candidate_status=mip_status,
        mip_candidate_message=mip_message,
        mip_candidate_elapsed_seconds=mip_elapsed,
        mip_candidate_objective=mip_objective,
        mip_candidate_exactly_feasible=mip_exactly_feasible,
        mip_candidate_attains_integer_dual=mip_attains_dual,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    model_group = parser.add_mutually_exclusive_group(required=True)
    model_group.add_argument("--physical-slots", type=int)
    model_group.add_argument("--global-max-slots", type=int)
    parser.add_argument("--time-limit-seconds", type=float, default=1800.0)
    parser.add_argument("--solve-mip-candidate", action="store_true")
    parser.add_argument("--lp-presolve", action="store_true")
    parser.add_argument("--mip-presolve", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    trace = json.loads(arguments.trace.read_text())
    windows = tuple(WindowTrace.from_dict(value) for value in trace["windows"])
    diagnostic: LpDiagnostic | None = None

    def capture(**kwargs: Any) -> NoReturn:
        nonlocal diagnostic
        diagnostic = _continuous_relaxation(
            physical_slots=(
                arguments.physical_slots
                if arguments.physical_slots is not None
                else arguments.global_max_slots
            ),
            time_limit_seconds=arguments.time_limit_seconds,
            solve_mip_candidate=arguments.solve_mip_candidate,
            lp_presolve=arguments.lp_presolve,
            mip_presolve=arguments.mip_presolve,
            **kwargs,
        )
        raise ModelCaptured

    original = optimizer.milp
    optimizer.milp = capture
    try:
        try:
            if arguments.physical_slots is not None:
                optimizer.solve_selection(windows, arguments.physical_slots)
            else:
                if len(windows) != 1:
                    raise ValueError("global diagnostic requires exactly one window")
                source = Path(trace["source"]["path"]).read_bytes()
                target = Path(trace["target"]["path"]).read_bytes()
                default_encoding = encode_file(windows, source, target)
                probe = Pattern((Atom(ADD, 255),))
                header_lengths = [len(encode_file_header()[0])]
                for q in range(1, arguments.global_max_slots + 1):
                    table = build_custom_table((probe,), q)
                    header_lengths.append(len(encode_file_header(table, q)[0]))
                optimizer.solve_global_selection(
                    windows[0],
                    arguments.global_max_slots,
                    file_header_lengths=header_lengths,
                    data_bytes=default_encoding.windows[0].data_length,
                    address_bytes=default_encoding.windows[0].address_length,
                )
        except ModelCaptured:
            pass
    finally:
        optimizer.milp = original
    if diagnostic is None:
        raise AssertionError("optimizer did not call the captured MILP backend")
    document = {
        "format": "vcdiff-android-strengthened-root-lp-diagnostic-v1",
        "evidence_boundary": (
            "Floating-point continuous-relaxation scouting result only; not an "
            "integer optimum, exact lower bound, or preregistered corpus label."
        ),
        "trace": str(arguments.trace),
        "model_kind": (
            "fixed_q" if arguments.physical_slots is not None else "global_q"
        ),
        "diagnostic": asdict(diagnostic),
    }
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
