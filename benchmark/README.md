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

The original floating HiGHS zero-gap evidence failed because a captured
feasible vector beat one reported dual bound. Exact labels now require the
frozen SCIP 10 numerically exact protocol, an independently integral dynamic
program attaining the same bound, emitted-byte equality, and two decoder
replays. All 48 stock traces have been independently replayed; 34 pairs meet
that exact-label standard and 14 remain unlabeled. This trace-complete but
exact-incomplete corpus supports neither an exact empirical distribution nor a
claim about broader VCDIFF tables, parses, or deployment behavior.

Prepare one frozen trace without invoking a custom-table solver or assigning an
outcome:

```bash
PYTHONPATH=src:. python3 benchmark/prepare_pair_trace.py \
  --pair-id source-zstd-v1.5.4-to-v1.5.6 \
  --output benchmark_artifacts_scip/source-zstd-v1.5.4-to-v1.5.6
```

The resulting sidecar checks the lock, stock-patch byte replay, strict Python
decoder, and unchanged historical decoder. Its semantic trace hash removes only
checkout/output path strings; source, target, baseline, and logical-window
content remain hashed. `benchmark/write_scip_partial_summary.py` validates all
available exact certificates and trace sidecars before writing the public
exact/unresolved frontier.
