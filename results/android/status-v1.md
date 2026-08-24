# Public Android DEX study status

**Trace-complete but oracle-incomplete and nonconfirmatory.** The corpus is frozen at 40 independent F-Droid projects, and every stock trace was exactly byte-replayed. The preregistered minimum is 30 exact oracle labels.

Exact: 6/40. Nonexact attempted: 21. Operationally skipped after trace replay: 13. Not attempted: 0.

The exact subset contains 3 pairs saving at least 1% and 3 zero-saving controls. Its weighted saving is 6.4987%, but this tractability-selected subset is not a valid estimate of the 40-project distribution.

## Exact labels

| Pair | Stock bytes | Exact bytes | Saving | q |
|---|---:|---:|---:|---:|
| `fdroid-com.jstappdev.e6bflightcomputer-19-to-20` | 251,942 | 240,417 | 11,525 (4.5745%) | 93 |
| `fdroid-com.phg.constellations-10004-to-10005` | 200,048 | 181,966 | 18,082 (9.0388%) | 93 |
| `fdroid-com.rtbishop.look4sat-322-to-323` | 61 | 61 | 0 (0.0000%) | 0 |
| `fdroid-hu.tagsoft.ttorrent.search-2-to-3` | 70 | 70 | 0 (0.0000%) | 0 |
| `fdroid-ohm.quickdice-45-to-48` | 32,517 | 30,627 | 1,890 (5.8123%) | 83 |
| `fdroid-v4lpt.vpt.f005.rsd-103-to-104` | 26 | 26 | 0 (0.0000%) | 0 |

Every exact row passed both decoders.

## Nonexact attempts

`fdroid-co.loubo.icicle-3-to-4`: stopped without an exact pair label (`witness_search_runtime_stop`). The retained q=93 bound is 460,307 bytes; it is not an attained optimum.

`fdroid-com.dergoogler.mmrl-22020-to-32432`: stopped without an exact pair label (`witness_search_runtime_stop`). The retained q=93 bound is 601,568 bytes; it is not an attained optimum.

`fdroid-com.google.android.stardroid-1704-to-1708`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 625,202 bytes; it is not an attained optimum.

`fdroid-com.ilm.sandwich-34-to-35`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-com.jellyshack.block6-6-to-7`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-com.kgurgul.cpuinfo-40302-to-40303`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-com.kolakek.pimiwidget-16-to-17`: stopped without an exact pair label (`scip_external_memory_safety_stop`). The retained q=93 bound is 321,904 bytes; it is not an attained optimum.

`fdroid-com.nbossard.packlist-18-to-19`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-com.onest8.onetimepad-201-to-202`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-com.vadimfrolov.duorem-5-to-6`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-gal.sli.singal-20-to-21`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-hashengineering.groestlcoin.wallet_test-73804-to-81401`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-io.gresse.hugo.anecdote-22-to-23`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-oppen.gemini.ariane-39-to-42`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 789,563 bytes; it is not an attained optimum.

`fdroid-org.evilsoft.pathfinder.reference-36-to-38`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 405,821 bytes; it is not an attained optimum.

`fdroid-org.fitchfamily.android.gsmlocation-73-to-74`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-org.kknickkk.spider-12-to-13`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-org.shadowice.flocke.andotp-38-to-39`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 536,289 bytes; it is not an attained optimum.

`fdroid-tech.techlore.plexus-217-to-219`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

`fdroid-tibarj.tranquilstopwatch-16-to-17`: stopped without an exact pair label (`fractional_root_gap`). The retained q=93 bound is 764,506 bytes; it is not an attained optimum.

`fdroid-uk.co.yahoo.p1rpp.secondsclock-6-to-7`: stopped without an exact pair label (`rational_dual_construction_timeout`). No exact fixed-q lower bound was produced.

## Post-hoc operational skips

`fdroid-cloud.valetudo.companion-15-to-16`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 1,148,504 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-com.chooloo.www.koler-79-to-82`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 473,436 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-com.fastaccess.github.libre-466-to-467`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 892,360 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-com.msb.bluecheese-6-to-303`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 906,317 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-com.zionhuang.music-19-to-20`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 832,627 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-de.c3nav.droid-14040501-to-18040700`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 700,352 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-de.christinecoenen.code.zapp-74-to-76`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 625,284 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-de.csicar.ning-200-to-201`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 817,624 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-de.devmil.muzei.bingimageofthedayartsource-9-to-18`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 720,777 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-it.feio.android.omninotes.foss-330-to-331`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 620,435 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-me.jfenn.alarmio-20-to-21`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 1,616,268 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-net.eneiluj.nextcloud.phonetrack-10-to-11`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 1,028,811 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

`fdroid-v4lpt.vpt.f006.yxn-100-to-102`: the stock trace was exactly byte-replayed, but the current q=93 solver was not started because the trace has 278,412 logical instructions, at or above the post-hoc 240,000-instruction host cutoff. This produces no exact bound and no oracle label.

## Exact-oracle scaling recovery

The E6 scaling-trigger pair has 70,913 logical instructions. Earlier global SCIP attempts were stopped at 8.5--8.8 GiB RSS and remain nonresults. The replacement proof removes LP-redundant aggregate big-M rows, replays exact rational dual vectors, uses q-monotonicity to transfer the q=80 bound to q=1..79, and matches q=93 with a binary decoded witness.

This certificate architecture has passed on the scaling trigger, but the preregistered corpus still requires at least 30 exact independent pairs. Approximate solver outputs will not be used as oracle labels.

A separate aggregate-free exact-SCIP formulation reproduced the QuickDice q=83 and E6 q=93 fixed-q optima in one node while retaining continuous path variables. It still reached a host memory safety stop on Pimi Widget, so it is a bounded validation tool rather than a general scaling solution.

After measured rational-bound construction misses began at 240,186 instructions, a disclosed post-hoc host policy stopped launching the current solver at 240,000 or above. Those pairs remain in the frozen schedule as trace-replayed operational skips with no bound and no label.

One exact zero-saving control had no eligible implicit-size table candidate. Its q=0 optimum was certified by the zero-variable structural branch and two decoder replays without invoking a MILP.

No predictor, reusable table bank, deployment experiment, or Superpack claim is supported at this stage.
