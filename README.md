# Exact restricted VCDIFF code-table optimization

This repository implements the immediate kill test proposed for VCDIFF custom
instruction tables. It instruments xdelta, jointly optimizes a legal custom
table and the single/pair parse, charges the complete RFC table header, emits a
standard VCDIFF patch, and writes a solver certificate.

> **Current status: exactness repaired; generalization remains incomplete.**
> SciPy/HiGHS presolve produced a false zero-gap optimum on a frozen trigger
> pair (8,261 bytes versus the true 8,254). The replacement backend uses SCIP
> 10 numerically exact mode, explicitly binary combinatorial variables,
> independently integral DP attainment, emitted-byte equality, and two decoder
> replays. It reproduces the trigger and every prior CP-SAT result. The frozen
> corpus is currently 25/48 exact, so its distribution is nonconfirmatory. See
> [`scip-partial-summary-v1.md`](results/generality/scip-partial-summary-v1.md).
> A separate replayed rational-LP-dual backend now handles the larger Android
> fixed-q models without weakening the exact label.

## Public Android DEX branch

A separate outcome-blind benchmark is frozen from the signed F-Droid main and
archive indices: 40 distinct public projects selected in fixed hash order,
with consecutive universal-APK releases and deterministic complete multidex
bundles. Corpus membership was frozen before any VCDIFF trace was generated.

The frozen 40-project schedule is trace-complete but oracle-incomplete. Every
stock trace was exactly byte-replayed and every pair is accounted: 6 exact
labels, 21 nonexact solver attempts, and 13 disclosed post-hoc resource-gate
skips. No pair was removed after observing an outcome.

Three exact pairs are favorable. QuickDice 45→48 is 32,517→30,627 bytes,
saving 1,890 bytes (5.8123%) at q=83. E6B Flight Computer 19→20 is
251,942→240,417 bytes, saving 11,525 bytes (4.5745%) at q=93. Constellations
10004→10005 is 200,048→181,966 bytes, saving 18,082 bytes (9.0388%) at q=93.
Three exact controls have zero gain: tTorrent Search 2→3 at 70→70, Look4Sat
322→323 at 61→61, and PowerTools f005 103→104 at 26→26 bytes. The last trace
has no eligible implicit-size table candidate, so its q=0 optimum is a
zero-variable structural certificate with two decoder replays and no MILP.

The second pair originally exposed an operational scaling stop: generic exact
SCIP exceeded 8 GiB process RSS. The replacement proof removes LP-redundant
aggregate big-M rows, verifies exact rational dual vectors with integer sparse
arithmetic, uses q-monotonicity to transfer the q=80 lower bound to q=1..79,
and matches q=93 with a binary witness, integral DP parse, emitted patch, and
two decoder replays. All 94 values q=0..93 are therefore covered. See the
compact [integer-dual summary](results/android/e6b-integer-dual-summary-v1.md)
and [independent replay ledger](results/android/e6b-fixed-q-bound-replay-v1.json).

A separate aggregate-free exact-SCIP formulation retains continuous path-flow
variables and only binary table-selection variables. It reproduced the
QuickDice q=83 and E6 q=93 fixed-q optima at one node, but a larger Pimi Widget
case still reached the host memory safety boundary without an exact result.
This is a bounded validation improvement, not a general scaling solution; see
the [validation ledger](results/android/strengthened-scip-validation-v1.json).
The same formulation supplies the attained q=93 row in the independently
replayed [Constellations composite certificate](results/android/constellations-exact-summary-v1.md).

Measured rational-bound construction misses began at 240,186 logical
instructions. A disclosed post-hoc host policy therefore preserves exact trace
preparation but does not launch the current q=93 solver at 240,000 instructions
or above. Such rows are operational skips, not solver attempts, lower bounds,
or compression labels. Below that cutoff, andOTP retained an independently
replayed q=93 full-patch lower bound of 536,289 bytes, but its best rounded
captured-model candidate remained 16 instruction bytes above the bound; it is
also nonexact and unlabeled.

The exactly solved subset totals 484,664→453,167 bytes (6.4987%), but it is
selected by solver tractability and is **not a distribution estimate or
generalization result**. The preregistered minimum is 30 exact Android pairs,
so no predictor, table bank, deployment experiment, or Superpack claim is
authorized. See
[`status-v1.md`](results/android/status-v1.md) and
[`preregistration-v1.json`](benchmark_android/preregistration-v1.json).

The starting point is the fixed-table dynamic program in the 2002
[VCDIFF/xdelta paper](https://www.usenix.org/legacy/events/usenix02/full_papers/korn/korn_html/)
and the custom-table wire format standardized by
[RFC 3284](https://www.rfc-editor.org/rfc/rfc3284.html).

The earlier exploratory run produced the following candidate improvements.
These rows motivated the generality experiment but their former exactness claim
is superseded by the validity stop above:

| Versioned tree pair | Stock xdelta3 | Earlier reported result | Saving | q |
|---|---:|---:|---:|---:|
| Zstandard 1.5.6→1.5.7 | 76,031 | 74,368 | 1,663 (2.1873%) | 93 |
| Open-VCDIFF 0.8.3→0.8.4 | 68,415 | 66,831 | 1,584 (2.3153%) | 93 |
| xdelta 3.0.10→3.0.11 | 5,787 | 5,787 | 0 (0.0000%) | 0 |
| Zstandard Win64 ZIP 1.5.6→1.5.7 | 1,719,956 | 1,719,956 | 0 (0.0000%) | 0 |

The three tree pairs aggregate to 150,233→146,986 bytes, a 3,247-byte
(2.1613%) reduction.  Including the compressed binary release changes the
byte-weighted aggregate to 1,870,189→1,866,942 bytes (0.1736%); it is a useful
q=0 negative control rather than evidence for custom tables on already
compressed packages. Their emitted patches still decode and their recorded
primal/dual values agree, but that agreement is no longer sufficient evidence
of optimality because of the presolve counterexample.

Both positive candidate results use all 93 replaceable pair-bank slots. Their gross
instruction savings are 2,284 and 2,205 bytes, respectively, before paying a
621-byte custom-header increment.  Hitting that boundary makes broader legal
table families—not a larger sweep of the same family—the natural next test.

Those exploratory gains justified the larger study, not an upstream-ready
result. The exact-SCIP replacement sweep is still incomplete: no full gain
distribution, predictor model, table bank, or deployment prototype is claimed.

## Reproduce one pair

Python 3.11+, a C compiler, Git, NumPy, SciPy, and pytest are required.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e . pytest
./scripts/reproduce_pair.sh SOURCE TARGET artifacts/my-pair 4 93
```

The output directory contains:

- `baseline-xdelta3.vcdiff`: the stock patch;
- `trace.json`: the complete logical xdelta trace;
- `default-table-optimal.vcdiff`: a byte-identical reconstruction;
- `restricted-code-table.bin`: the 1,536-byte selected table when `q>0`;
- `restricted-parse.json`: the fixed-table DP parse ledger;
- `restricted-optimal.vcdiff`: the emitted optimum;
- `certificate.json`: hashes, byte counts, model bounds, restrictions, and
  decoder replay records;
- `report.md`: a concise pair-level result.

Replay a certificate independently with:

```bash
PYTHONPATH=src python3 -m vcdiff_opt.cli verify \
  --certificate artifacts/my-pair/certificate.json \
  --custom-table-decoder build/xdelta/xdelta3-rfc-custom-decoder
```

The legacy verifier still uses the historical HiGHS path. Replay the decisive
counterexample with:

```bash
./scripts/reproduce_validity_stop.sh
```

## Frozen generality corpus

The outcome-blind acquisition and analysis contracts remain useful and are
documented in [`benchmark/README.md`](benchmark/README.md). They lock 48 usable
version pairs and 67 artifacts spanning source trees, compiled code, structured
data, and compressed controls. The exact-SCIP sweep currently covers 25/48
pairs, so the preregistered generality gate has not been evaluated.

## Reproduce the pinned corpus

```bash
./scripts/reproduce_corpus.sh
```

This fetches the earlier pinned revisions, creates deterministic metadata-light
tree blobs, checks their SHA-256 values, reruns the diagnostic optimizer and
both decoder replays, and regenerates `results/corpus-summary.json` and
`results/corpus-summary.md`. Those outputs are not restored to exact status by
reproduction.

## Code map

- `patches/xdelta3-trace.patch` — opt-in logical trace instrumentation.
- `src/vcdiff_opt/default_table.py` — exact RFC default table.
- `src/vcdiff_opt/parser.py` — fixed-table linear dynamic program.
- `src/vcdiff_opt/optimizer.py` — fixed-q and global-q MILPs.
- `src/vcdiff_opt/codec.py` — canonical table delta and RFC patch emitter.
- `src/vcdiff_opt/decoder.py` — strict independent decoder.
- `src/vcdiff_opt/study.py` and `verify.py` — certificate production/replay.
- `benchmark/integer_dual_adapter.py` — integer-arithmetic replay of rational
  LP lower bounds and matching binary witnesses.
- `benchmark/strengthened_scip_adapter.py` — aggregate-free exact SCIP with
  continuous path variables and binary table selections.
- `benchmark_android/run_fixed_q_integer_dual.py` and
  `verify_fixed_q_bound_sweep.py` — fixed-q proof construction and independent
  bound replay for the public DEX branch.
- `benchmark_android/finalize_zero_candidate_pair.py` — solver-free exact
  certification when the restricted family has no eligible table candidate.
- `benchmark_android/record_scaling_gate_skip.py` — fail-visible recording of
  trace-replayed rows screened by the post-hoc host cutoff.
- `docs/model.md` — formulation and exactness argument.
- `docs/implementation-audit.md` — RFC and decoder audit.
- `corpus/manifest.json` — immutable corpus provenance.

The governing evidence boundary is deliberate: a reported floating-point zero
gap is not an exact certificate when an independently feasible vector beats its
dual bound. Exact labels require either the locked exact-SCIP protocol or an
integer-replayed rational LP lower bound with a matching binary witness, plus
independent integral attainment, emitted-byte equality, and decoder replay.
Incomplete corpora remain explicitly incomplete.
