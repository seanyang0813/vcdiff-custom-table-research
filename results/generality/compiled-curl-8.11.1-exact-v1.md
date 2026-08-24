# Exact compiled-curl checkpoint

The frozen compiled curl 8.11.0 to 8.11.1 pair is exactly certified at
169,800 to 160,563 bytes: a 9,237-byte (5.4399%) reduction with q=93.

The locked SCIP 10.0.2 run used numerically exact mode and one thread. Its
global primal and dual objectives both equal 46,261 at one node; the independent
integral dynamic program attains that value. The emitted patch hash is
`7aa301f6e3d4e22e21bf1fc8ad9ff6013f82c325505d78532c2c727dc6ad737a`,
and both the strict Python decoder and the unchanged historical xdelta decoder
reproduce the frozen target hash.

The run took 3,632 seconds (1:00:32 wall time), peaked at 4,896,992 KiB RSS,
and used no swap. The compact machine-readable ledger is
[`compiled-curl-8.11.1-exact-v1.json`](compiled-curl-8.11.1-exact-v1.json).

With the ignored corpus artifacts present, replay the certificate, canonical
dynamic-program parse, emitted patch, and both decoders with:

```bash
PYTHONPATH=src:. python3 -m vcdiff_opt.cli verify \
  --certificate benchmark_artifacts_scip/compiled-curl-8.11.0-to-8.11.1/certificate.json \
  --custom-table-decoder build/xdelta/xdelta3-rfc-custom-decoder
```

This is exact only for the frozen pair, fixed one-window stock trace, and locked
restricted q=0..93 table family. It is a tractability-selected corpus label,
not a corpus distribution, predictor, deployment, broader-table, or Superpack
result.
