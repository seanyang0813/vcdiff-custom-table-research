# Public Android DEX study status

**Partial and nonconfirmatory.** The corpus is frozen at 40 independent F-Droid projects, but the preregistered minimum is 30 exact labels.

Exact: 1/40. Nonexact attempted: 1. Not attempted: 38.

## Exact result available

`fdroid-ohm.quickdice-45-to-48`: 32,517 → 30,627 bytes, saving 1,890 bytes (5.8123%), q=83. Both decoders passed.

## Scaling stop

The second scheduled pair has 70,913 logical instructions. Global binary SCIP was stopped at 8.5 GiB RSS; the continuous-path relaxation was stopped at 8.8 GiB without a bound. Fixed q=1 proved exactly but required 438 seconds and 5.67 GiB, so q=0..93 enumeration is not practical.

The next required step is a problem-specific exact decomposition or stronger certificate. Approximate solver outputs will not be used as oracle labels.

No predictor, reusable table bank, deployment experiment, or Superpack claim is supported at this stage.
