from __future__ import annotations

from copy import deepcopy

import pytest

from vcdiff_opt.verify import _verify_exact_scip_claim


def exact_claim() -> dict:
    return {
        "custom_evaluations": [{}],
        "global_optimum": {
            "file_bytes": 160563,
            "solver": {
                "instruction_bytes": 45629,
                "patch_bytes": 160563,
                "patch_dual_bound": 160563,
                "solver_gap": 0,
                "variable_patch_bytes": 46261,
            },
        },
        "tools": {
            "independent_integer_proof": {
                "api": "PySCIPOpt / SCIP numerically exact mode",
                "pyscipopt_version": "6.2.1",
                "scip_version": "10.0.2",
                "settings": {
                    "limits/memory_mb": 6000,
                    "limits/time_seconds_per_model": 7200,
                    "lp/threads": 1,
                    "parallel/maxnthreads": 1,
                    "randomization/lpseed": 0,
                    "randomization/permutationseed": 0,
                    "randomization/permuteconss": False,
                    "randomization/permutevars": False,
                    "randomization/randomseedshift": 0,
                },
                "calls": [
                    {
                        "best_bound": 53725,
                        "exact_mode": True,
                        "mps_sha256": "fixed-q-mps",
                        "objective": 53725,
                        "returned_solution_source": "validated_scipy_no_presolve_hint",
                        "threads": 1,
                    },
                    {
                        "best_bound": 46261,
                        "exact_mode": True,
                        "mps_sha256": "global-mps",
                        "objective": 46261,
                        "returned_solution_source": "validated_scipy_no_presolve_hint",
                        "threads": 1,
                    },
                ],
            }
        },
    }


def test_exact_scip_claim_accepts_equal_primal_dual_records() -> None:
    result = _verify_exact_scip_claim(exact_claim())
    assert result["patch_primal"] == result["patch_dual"] == 160563
    assert result["global_mps_sha256"] == "global-mps"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("best_bound", 46260),
        ("exact_mode", False),
        ("returned_solution_source", "unvalidated_hint"),
        ("threads", 2),
    ],
)
def test_exact_scip_claim_rejects_unlocked_call(field: str, value: object) -> None:
    claim = deepcopy(exact_claim())
    claim["tools"]["independent_integer_proof"]["calls"][-1][field] = value
    with pytest.raises(ValueError, match="invalid locked exact-SCIP call"):
        _verify_exact_scip_claim(claim)


def test_exact_scip_claim_rejects_patch_bound_mismatch() -> None:
    claim = exact_claim()
    claim["global_optimum"]["solver"]["patch_dual_bound"] -= 1
    with pytest.raises(ValueError, match="bound does not match"):
        _verify_exact_scip_claim(claim)
