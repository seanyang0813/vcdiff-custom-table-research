# Frozen generality benchmark

This benchmark measures the exact gain distribution of the existing restricted
VCDIFF code-table optimizer on real version pairs. It does not alter
`src/vcdiff_opt/optimizer.py`.

The outcome-blind contract is split into four ledgers:

- `preregistration-v1.json` fixes the 51 requested pairs, project-held-out
  splits, hypotheses, metrics, and continuation gate.
- `deviations.jsonl` records acquisition corrections made before any
  confirmatory VCDIFF trace. Three oversized SQLite source-tree pairs were
  excluded without replacement, leaving 48 pairs.
- `artifact-lock-v1.json` fixes the 67 exact input artifacts used by those 48
  pairs, including hashes, byte counts, provenance, build logs, and toolchain.
- `analysis-spec-v1.json` fixes feature definitions, model selection, gate
  thresholds, and the conditional table-bank protocol.

Each JSON lock has an adjacent SHA-256 ledger. `execution-deviations.jsonl`
records operational corrections discovered after tracing began; these cannot
change pair membership, optimizer behavior, or selection based on outcomes.

Run the complete workflow with:

```bash
./scripts/reproduce_generality.sh
```

The slow steps are resumable. Pair-local patches, traces, parses, certificates,
and reports are written beneath ignored `benchmark_artifacts/`; acquisition and
build caches live beneath ignored `benchmark_data/`, `benchmark_downloads/`,
and `benchmark_work/`. Aggregate replayable results are written to
`results/generality/`.

The intended evidence boundary was a zero-gap optimum within the frozen
one-window, fixed-xdelta-trace, q=0..93 canonical prefix-replacement family.
That prerequisite failed: a captured feasible vector beats a reported dual
bound. Consequently the partial certificates are diagnostic only, and the
corpus currently supports neither an exact empirical distribution nor a claim
about broader VCDIFF tables or parses.
