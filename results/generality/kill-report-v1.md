# VCDIFF generality study: validity stop

## Outcome

The preregistered exact-gain study stopped before distribution or predictor
analysis. The frozen optimizer reported a q=1 MILP primal and dual of **8,261
instruction bytes with zero gap** on
`compressed-zstd-tar-gz-v1.5.4-to-v1.5.5`, while its selected table replayed in
the independent dynamic program at **8,258 bytes**.

This is not a rounding discrepancy. A vector reconstructed from that DP parse
has objective 8,258 and satisfies the captured MILP constraint matrix with
maximum violation **0**. Re-solving the identical matrix with HiGHS presolve
disabled proves **8,254**, and the independent DP also obtains 8,254.

Therefore the zero-gap result produced with presolve enabled is a false
optimality certificate. The optimizer file remains byte-identical to its frozen
SHA-256 `aac3d7906c7b7f6e26a98f95691f34b599057fc477bef9b2675500a302c32b51`.

## Consequences

- The full 48-pair exact gain distribution was **not** computed.
- The 10 certificates emitted before the abort are retained as
  diagnostic artifacts, but none is promoted into the confirmatory exact
  distribution because they share the invalidated solver execution path.
- Predictor fitting and change-distance inference were **not** run.
- The preregistered generality gate is **not evaluated**, hence it does not pass.
- No reusable table bank or deployment prototype was built.

The acquisition result remains usable: 48 frozen pairs across source trees,
compiled code, structured data, and compressed controls are locked in
`benchmark/artifact-lock-v1.json`. Three preregistered SQLite source-tree pairs
were excluded before tracing because the common source artifact exceeded the
64 MiB limit.

## Replay

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python3 benchmark/capture_optimizer_counterexample.py \
  --pair-id compressed-zstd-tar-gz-v1.5.4-to-v1.5.5 --physical-slots 1
```

The replay ledger is
`results/generality/optimizer-counterexamples/compressed-zstd-tar-gz-v1.5.4-to-v1.5.5-q1.json`.

Restarting the oracle sweep requires permission to change the optimizer
execution path and then revalidate exactness. That is outside the explicit
instruction not to modify the optimizer in this study.
