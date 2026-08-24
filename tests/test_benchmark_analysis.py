from __future__ import annotations

import numpy as np

from benchmark.analyze_corpus import tune_threshold
from benchmark.extract_features import (
    distribution_fields,
    nonoverlap_coverage,
    ranked,
)


def test_ranked_distribution_has_deterministic_ties() -> None:
    from collections import Counter

    counts = Counter({"B": 2, "A": 2})
    assert ranked(counts) == [("A", 2), ("B", 2)]
    fields = distribution_fields("single", counts)
    assert fields["single_entropy"] == 1.0
    assert fields["single_normalized_entropy"] == 1.0
    assert fields["single_herfindahl"] == 0.5
    assert fields["single_top1_mass"] == 0.5


def test_nonoverlap_pair_coverage_uses_maximum_matching() -> None:
    windows = [["A", "B", "A", "B", "A"]]
    allowed = {"A+B", "B+A"}
    assert nonoverlap_coverage(windows, allowed, 5) == 4 / 5


def test_validation_threshold_obeys_precision_then_recall_rule() -> None:
    actual = np.asarray([0, 0, 1, 1])
    probability = np.asarray([0.1, 0.3, 0.4, 0.9])
    result = tune_threshold(actual, probability)
    assert result is not None
    assert result["threshold"] == 0.4
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
