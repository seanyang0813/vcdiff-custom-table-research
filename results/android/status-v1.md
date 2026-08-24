# Public Android DEX study status

**Partial and nonconfirmatory.** The corpus is frozen at 40 independent F-Droid projects, but the preregistered minimum is 30 exact labels.

Exact: 4/40. Nonexact attempted: 6. Not attempted: 30.

## Exact result available

`fdroid-com.jstappdev.e6bflightcomputer-19-to-20`: 251,942 → 240,417 bytes, saving 11,525 bytes (4.5745%), q=93. Both decoders passed.

## Exact result available

`fdroid-com.rtbishop.look4sat-322-to-323`: 61 → 61 bytes, saving 0 bytes (0.0000%), q=0. Both decoders passed.

## Exact result available

`fdroid-hu.tagsoft.ttorrent.search-2-to-3`: 70 → 70 bytes, saving 0 bytes (0.0000%), q=0. Both decoders passed.

## Exact result available

`fdroid-ohm.quickdice-45-to-48`: 32,517 → 30,627 bytes, saving 1,890 bytes (5.8123%), q=83. Both decoders passed.

## Nonexact attempts

`fdroid-co.loubo.icicle-3-to-4`: stopped without an exact pair label (`witness_search_runtime_stop`). The retained q=93 bound is 460,307 bytes; it is not an attained optimum.

`fdroid-com.dergoogler.mmrl-22020-to-32432`: stopped without an exact pair label (`witness_search_runtime_stop`). The retained q=93 bound is 601,568 bytes; it is not an attained optimum.

`fdroid-com.kolakek.pimiwidget-16-to-17`: stopped without an exact pair label (`scip_external_memory_safety_stop`). The retained q=93 bound is 321,904 bytes; it is not an attained optimum.

`fdroid-oppen.gemini.ariane-39-to-42`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 789,563 bytes; it is not an attained optimum.

`fdroid-org.evilsoft.pathfinder.reference-36-to-38`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 405,821 bytes; it is not an attained optimum.

`fdroid-tibarj.tranquilstopwatch-16-to-17`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 764,506 bytes; it is not an attained optimum.

## Exact-oracle scaling recovery

The second scheduled pair has 70,913 logical instructions. Earlier global SCIP attempts were stopped at 8.5--8.8 GiB RSS and remain nonresults. The replacement proof removes LP-redundant aggregate big-M rows, replays exact rational dual vectors, uses q-monotonicity to transfer the q=80 bound to q=1..79, and matches q=93 with a binary decoded witness.

This certificate architecture has passed on the scaling trigger, but the preregistered corpus still requires at least 30 exact independent pairs. Approximate solver outputs will not be used as oracle labels.

A separate aggregate-free exact-SCIP formulation reproduced the QuickDice q=83 and E6 q=93 fixed-q optima in one node while retaining continuous path variables. It still reached a host memory safety stop on Pimi Widget, so it is a bounded validation tool rather than a general scaling solution.

No predictor, reusable table bank, deployment experiment, or Superpack claim is supported at this stage.
