# Real-corpus decision

| Pair | Target bytes | Trace instructions | Stock patch | Restricted optimum | Savings | q | Primal = dual |
|---|---:|---:|---:|---:|---:|---:|---:|
| Zstandard v1.5.6→v1.5.7 | 8,383,227 | 19,968 | 76,031 | 74,368 | 1,663 (2.1873%) | 93 | 74,368 |
| Open-VCDIFF openvcdiff-0.8.3→openvcdiff-0.8.4 | 2,606,221 | 18,552 | 68,415 | 66,831 | 1,584 (2.3153%) | 93 | 66,831 |
| xdelta v3.0.10→v3.0.11 | 2,157,414 | 1,436 | 5,787 | 5,787 | 0 (0.0000%) | 0 | 5,787 |
| Zstandard Win64 ZIP v1.5.6 release asset→v1.5.7 release asset | 1,747,181 | 2,179 | 1,719,956 | 1,719,956 | 0 (0.0000%) | 0 | 1,719,956 |

Aggregate: 1,870,189→1,866,942 bytes, saving 3,247 bytes (0.1736%).

On the two positive pairs, q=93 uses the full replaceable pair bank. Gross instruction-section savings are 2,284 and 2,205 bytes; each canonical custom header costs 621 bytes more than the default header.

Decision: **continue the restricted research**. Two independent project tree pairs clear the provisional 0.3% gate. The small xdelta update and compressed Win64 release are exact q=0 negative controls.

This is not an upstream-readiness claim. The proof is scoped to the recorded traces and canonical pair-bank family, and current xdelta deliberately lacks custom-table decode support.
