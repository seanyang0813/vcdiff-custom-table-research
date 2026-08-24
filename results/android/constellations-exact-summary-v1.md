# Composite exact result on public Android DEX

Stock patch: 200,048 bytes. Exact restricted q=0..93 optimum: 181,966 bytes at q=93. Saving: 18,082 bytes (9.0388%).

The proof covers all 94 slot counts. It combines the exact q=0 default-table dynamic program, independently replayed rational LP dual bounds for q=80..92, monotonic transfer from q=80 to q=1..79, and an exact aggregate-free SCIP q=93 result with equal primal and dual. The q=93 model fingerprint was rebuilt independently, its integral parse attains 34,116 instruction bytes, and both decoders reproduce the frozen target. The closest competitor is q=92, whose exact patch lower bound is 181,975 bytes—9 bytes above the incumbent.

This is the fifth exact pair in a frozen 40-project public F-Droid surrogate. Three of the five exact pairs save at least 1%, but the preregistered minimum is 30 exact pairs; no predictor, reusable table bank, deployment claim, or Meta/Superpack claim is authorized.
