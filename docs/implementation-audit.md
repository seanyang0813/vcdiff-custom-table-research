# Format and implementation audit

> **Superseding validity result (2026-08-23):** the wire-format and decoder
> checks below remain useful, but the frozen optimizer's HiGHS presolve path has
> a replayable false-optimum counterexample. These checks do not establish
> global optimization exactness. See `results/generality/kill-report-v1.md`.

## RFC layout used here

[RFC 3284](https://www.rfc-editor.org/rfc/rfc3284.html) represents a custom
code table as 1,536 bytes in six 256-byte arrays: `inst1`, `inst2`, `size1`,
`size2`, `mode1`, and `mode2`.  The outer file header carries the length of the
code-table data, the near/same cache sizes, and a nested default-table VCDIFF
delta that reconstructs those bytes.

The encoder in `codec.py` writes that RFC length field and uses a deterministic
six-block ADD/COPY delta.  The in-project strict decoder checks reserved bits,
length boundaries, table legality, address-cache behavior, section
consumption, and final target size.

## xdelta trace fidelity

The trace build pins current xdelta commit
`9822b17313263d458b80511b08124971fc0e04fa`.  The 49-line opt-in patch logs
logical instructions after COPY mode selection and before fixed-table opcode
pairing.  Normal encoding behavior is unchanged when the macro is disabled.

The study disables checksums, secondary compression, and application headers,
and forces one target window.  Re-encoding the captured trace with the RFC
default table is required to reproduce the stock xdelta patch byte-for-byte;
the study aborts if it does not.  This is a stronger trace-fidelity check than
matching file size alone.

## Independent decoder choice

Current xdelta 3.2.x parses the custom-table length and cache fields but then
deliberately returns `XD3_UNIMPLEMENTED` with `"VCD_CODETABLE support was
removed"`.  It cannot serve as a successful custom-table replay target.

The independent replay binary is instead built, without source modifications,
from xdelta-gpl commit
`98bc4523a0c5d1a0743da4261e41a431a66acf2d`, the parent of the removal commit.
That decoder consumes the RFC length field and generically reconstructs the
custom table.  It is compiled with its upstream
`GENERIC_ENCODE_TABLES=1` configuration switch but no source modifications.
Every reported patch is decoded both by it and by the strict Python
implementation, and both outputs must equal the target SHA-256.

Google Open-VCDIFF was inspected but not used as the conformance oracle.  Its
custom-table path is tied to its SDCH-format behavior and parses near/same
values immediately after the indicator rather than the RFC code-table-data
length used by xdelta and RFC 3284.

## Pinned components

| Purpose | Repository / commit |
|---|---|
| Trace and stock encoder | `jmacd/xdelta` at `9822b17313263d458b80511b08124971fc0e04fa` |
| Unchanged custom-table decoder | `jmacd/xdelta-gpl` at `98bc4523a0c5d1a0743da4261e41a431a66acf2d` |
| Numerical MILP solver | SciPy `milp` / HiGHS, with zero requested relative gap |

The certificate records paths, commits, hashes, complete trace and parse
ledgers, emitted table and patch, the exact byte decomposition, and both solver
bounds.
