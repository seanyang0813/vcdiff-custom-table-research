"""Exact SCIP over the aggregate-free strengthened fixed-q model.

This is a separate experimental adapter.  It does not modify the frozen
exact-SCIP amendment or its locked adapter.  The transformation is regenerated
by ``integer_dual_adapter._standardize``: aggregate big-M activation rows are
replaced by their individual ``x_occ <= y_pattern`` implications, while path
variables remain continuous and table variables remain binary.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint
from scipy.sparse import vstack

from benchmark.integer_dual_adapter import _standardize
from benchmark.scip_exact_adapter import ScipExactAdapter, ScipExactCall


class StrengthenedScipAdapter:
    """Callable SciPy-MILP replacement using exact SCIP after strengthening."""

    def __init__(
        self,
        *,
        time_limit_seconds: float = 1800.0,
        memory_limit_mb: float = 6000.0,
        display: bool = False,
    ) -> None:
        self.inner = ScipExactAdapter(
            scipy_no_presolve_hint=False,
            display=display,
            promote_all_binary=False,
            strengthen_activation_links=False,
            time_limit_seconds=time_limit_seconds,
            memory_limit_mb=memory_limit_mb,
        )
        self.model_fingerprints: list[str] = []

    @property
    def calls(self) -> list[ScipExactCall]:
        return self.inner.calls

    def __call__(
        self,
        *,
        c: Any,
        integrality: Any,
        bounds: Any,
        constraints: Any,
        options: dict[str, Any] | None = None,
    ) -> Any:
        standard = _standardize(
            c=c,
            integrality=integrality,
            bounds=bounds,
            constraints=constraints,
        )
        matrix = vstack(
            (standard.equality_matrix, standard.inequality_matrix),
            format="csr",
        )
        row_lower = np.concatenate(
            (
                standard.equality_rhs,
                np.full(
                    standard.inequality_matrix.shape[0],
                    -np.inf,
                    dtype=float,
                ),
            )
        )
        row_upper = np.concatenate(
            (standard.equality_rhs, standard.inequality_rhs)
        )
        self.model_fingerprints.append(standard.fingerprint)
        return self.inner(
            c=standard.objective,
            integrality=standard.integrality,
            bounds=Bounds(standard.lower_bounds, standard.upper_bounds),
            constraints=LinearConstraint(matrix, row_lower, row_upper),
            options=options,
        )
