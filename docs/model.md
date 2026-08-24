# Exact restricted model

> **Validity note (2026-08-23):** the frozen generality corpus produced a
> feasible DP/MILP vector below a HiGHS presolve result that reported zero gap.
> Therefore the exactness argument below is conditional on a correct MILP solve;
> the current presolve-enabled execution does not satisfy that condition. See
> `results/generality/kill-report-v1.md` and the replayable counterexample ledger.

## Scope

Fix one logical ADD/RUN/COPY trace produced by xdelta after match selection and
COPY address-mode selection, but before opcode pairing.  Data bytes, COPY
addresses, the source segment, and the RFC address caches (near=4, same=3) are
therefore fixed.

The optimized table family preserves RFC default opcodes 0..162.  For a chosen
integer `q`, it replaces the prefix 163..`163+q-1` of the 93-entry default pair
bank with at most `q` distinct patterns observed in the trace.  A pattern is an
exact implicit-size single or consecutive pair

```text
(type1, size1, mode1 [, type2, size2, mode2]),   1 <= size_i <= 255.
```

Unused physical slots duplicate one selected entry.  Entries after the prefix
are unchanged.  Thus every installed pattern costs one instruction byte while
generic preserved entries remain available unless their particular pair-bank
opcode has been overwritten.

This is a strict subset of all legal 256-entry VCDIFF tables.  In particular,
it does not replace generic single entries, introduce size-zero pair halves,
change address caches, change the xdelta match trace, or optimize the nested
table-delta parser.

## Variables and constraints

For every trace position, construct all legal width-one and width-two parse
edges.  Let `x_e` select an edge, `y_p` install observed pattern `p`, and `z_q`
select exactly one replacement count in `0..Q`, where `Q <= 93`.

The model imposes:

```text
sum(e covers i) x_e = 1                         for every trace instruction i
sum(e uses p) x_e <= occurrences(p) * y_p      for every candidate p
sum(p) y_p <= sum(q) q * z_q
sum(q) z_q = 1
```

For a preserved default pair opcode that disappears once `q >= r`, its edge is
additionally bounded by `sum(q < r) z_q`.  Custom-pattern edges are available
only through their corresponding `y_p`.

The `y` and `z` variables are binary.  In the fixed-q model, parse variables can
remain continuous: once table choices are fixed, the remaining interval-cover
matrix has the consecutive-ones property and is totally unimodular.  Its
extreme points are integral and correspond exactly to a tiling of the
instruction trace by legal single/pair opcodes.

## Exact byte objective

For each `q`, the implementation precomputes `H_q`, the byte length of the
complete RFC file header including the canonical nested table delta.  Its
length depends on `q`, not on the byte values of the installed patterns: each
of the six 256-byte table fields is represented by fixed COPY regions and one
`q`-byte ADD region.

The data and address sections are invariant.  The remaining non-linearities
are the base-128 length fields for the instruction section and delta encoding.
The global-q MILP enumerates their feasible byte-length regimes with one-hot
binary state variables.  Intersecting the parse polytope with these regime
bounds need not preserve total unimodularity, so continuous parse variables
are treated as a lower-bound relaxation.  The implementation independently
runs the integral fixed-table DP on the selected table and refuses to issue a
certificate unless that construction attains the relaxation bound.  Its
variable objective is

```text
instruction bytes
+ H_q
+ sizeof_varint(instruction bytes)
+ sizeof_varint(delta encoding length).
```

The certificate adds the invariant window prefix, target-length field,
section-length fields, data section, and address section.  Therefore
`patch_bytes` and `patch_dual_bound` are lower and upper bounds on the complete
file size in this restricted family, not merely on the instruction section.

## Why the certificate is exact

Every table and parse in the restricted family induces a feasible MILP point
with the same byte cost, while relaxing parse integrality can only decrease the
model optimum.  The solver dual is therefore a valid lower bound.  The selected
table is then parsed by the independent integral dynamic program; the
certificate is emitted only if that legal construction has exactly the same
instruction and full-patch byte counts.  The varint state and precomputed
header cost reproduce the emitted file's remaining bytes.  Equal integer
primal and dual objectives at zero MIP gap, together with this attained DP
construction, therefore give matching lower and upper bounds.

The verifier performs the converse construction independently: it rebuilds
the table, reruns the fixed-table dynamic program, regenerates the full patch,
checks the parse ledger and hashes, reruns the global MILP, and decodes with two
decoders.

## Evidence boundary

The result is global over `q=0..Q` and all observed candidate choices only in
the canonical family above.  It is not evidence of an optimum over every legal
VCDIFF table, over alternate nested table-delta encoders, over multiple target
windows, or over traces that a table-aware string matcher might produce.
