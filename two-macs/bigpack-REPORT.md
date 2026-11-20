# A DeepSeek-V4.1-Flash pack that needs two Mac Studios: speed on the pair

> Lab notes from the measuring sessions, lightly edited for publication: machine names, paths and addresses are
> replaced, and the two Macs are called Mac 1 (rank 0) and Mac 2. Scripts named here that were tied to our machines
> (`arm.sh`, `pair.sh`, `package.sh`, `pair-big.sh`) and the raw `results/` and log folders are not in this branch.
> The benchmark and quality scripts are in `two-macs/scripts/`; the code is this branch's commits.

Measured 2026-11-20 on two Mac Studios (M5 Ultra, 256 GB each) joined by Thunderbolt 5 RDMA, mlx-serve `--dist tensor`. Effort max, temperature 0, every run under a watchdog.

## Final result, after the fixes (12:00)

Fixes followed the first measurements below. The final setup is the patched build `a96cc1e536c3` (same decode code as `afab170a83d7`, on which the stream and decode rows were measured) with `DSV41_TP_SUM=bf16` added, on a hybrid pack folder, `DeepSeek-V4.1-Flash-1017-oQ4-fullengram`: the big pack's weights with the released Engram tables (symlinks only; both sets of files were already on the Studios). Every part of the model is now at released precision.

| | one Studio, 3.0bpw | pair, big pack, final | change | before the fixes |
|---|---|---|---|---|
| 1 stream, real prompts, tok/s | 79.0 | 91.9 / 93.4 | **+16% / +18%** | 88.4 / 90.2 |
| 2 streams | 94.2 | 118.7 / 117.3 | **+26% / +25%** | 115.8 / 117.3 |
| 4 streams | 124.0 | 151.2 / 154.3 | **+22% / +24%** | 147.4 / 151.9 |
| 8 streams | not measured | 176.9 / 177.7 | | 172.1 / 173.3 |
| decode bench, DSpark | 79.7 | 102.7 (95.3-112.7) | **+29%** | 101.4 |
| decode bench, plain | 65.8 | 82.0 | **+25%** | 77.3 |
| cold 26,800-token prompt | 6.89 s | 7.40-7.43 s | **8% later** | 8.87 s (29% later) |
| follow-up on a cached prompt | 0.115-0.145 s | 0.09-0.11 s | sooner | 0.10-0.11 s |
| new question behind a shared system prompt | 0.30-0.31 s | 0.23-0.26 s | about 20% sooner | 0.24-0.27 s |
| first chunk, short prompt | 0.146-0.162 s | 0.13-0.19 s | same | 0.14-0.22 s |

Quality check on the final setup: 48/48 plain, `--par 4` and `--sys 9000` (run on every kept fix).

**Confirmed on the public pack (15:00).** The same build and switches were run on `mlx-community/DeepSeek-V4.1-Flash-1017-oQ4e-ngram-mtp` (commit `d8b79a787450`), which is the hybrid as one public download: the same 80 weight files plus the released Engram tables. Label `ngram-final`. This is the pack to name as tested.

| | hybrid folder (`fe-sumbf16`) | public pack (`ngram-final`) | first token on the public pack, median / worst |
|---|---|---|---|
| 1 stream, tok/s | 91.9 / 93.4 | 92.8 / 93.6 | 0.22 / 0.22 s |
| 2 streams | 118.7 / 117.3 | 116.4 / 116.4 | 0.25 / 0.34 s |
| 4 streams | 151.2 / 154.3 | 151.1 / 150.8 | 0.42 / 0.71 s |
| 8 streams | 176.9 / 177.7 | 178.5 / 179.6 | 0.80 / 1.53 s |
| decode bench, DSpark | 102.7 (95.3-112.7) | 103.5 (95.9-114.7) | 0.22 s |
| cold 26,800-token prompt | 7.40-7.43 s | 7.40-7.41 s | |
| follow-up on a cached prompt | 0.09-0.11 s | 0.09-0.11 s | |
| new question behind a shared 26,800-token prompt | 0.23-0.26 s | 0.25-0.26 s | |
| quality, plain / `--par 4` / `--sys 9000` | 48/48 each | 48/48 each, no stray tokens in 144 answers | |

Every difference is inside the run-to-run spread. The load log shows the same fused paths on both ranks.

**Stock against patched on the public pack (15:15).** Stock v26.11.3 was run on the same pack (labels `ngram-stock`, `ngram-stock-plain`). It loads without changes. This is the like-for-like comparison; the earlier stock figures further down were on the pack with 4-bit Engram tables.

| public pack, pair | stock v26.11.3 | patched (`ngram-final`) | patched over stock | stock vs one Studio 3.0bpw |
|---|---|---|---|---|
| 1 stream, tok/s (two passes) | 74.0 / 74.5 | 92.8 / 93.6 | **+25%** | −6% |
| 2 streams | 99.5 / 99.2 | 116.4 / 116.4 | **+17%** | +6% |
| 4 streams | 135.0 / 135.9 | 151.1 / 150.8 | **+11%** | +9% |
| 8 streams | 171.2 / 172.1 | 178.5 / 179.6 | **+4%** | |
| first token at 1 / 2 / 4 / 8 streams, median | 0.22 / 0.25 / 0.44 / 0.84 s | 0.22 / 0.25 / 0.42 / 0.80 s | same | |
| first token, worst | 0.23 / 0.35 / 0.79 / 1.61 s | 0.22 / 0.34 / 0.71 / 1.53 s | same | |
| decode bench, DSpark | 78.0 (68.1-89.5) | 103.5 (95.9-114.7) | **+33%** | −2% |
| decode bench, plain | 62.9 | 82.0 (hybrid folder; not rerun on this pack) | **+30%** | −4% |
| cold 26,800-token prompt | 7.43 s | 7.40 s | same | 8% later |
| follow-up on a cached prompt | 0.10-0.11 s | 0.09-0.11 s | same | |
| new question behind a shared 26,800-token prompt | 7.4-7.5 s (nothing cached) | 0.25-0.26 s | **97% sooner** | |
| first chunk, short prompt | 0.13-0.19 s | 0.12-0.19 s | same | |

- The cold-prompt time is the same on stock and patched, so that gain came from the pack's released Engram tables, not from our patches.
- Stock's 1-stream figure is higher here (74) than on the 4-bit-Engram pack (65-68).

What each fix did:

| fix | result | kept |
|---|---|---|
| Released Engram tables in place of the pack's 4-bit ones (hybrid folder, no code) | cold 26.8k prompt 8.87 s to 7.43 s; decode-bench first token back to 0.17-0.23 s from 0.32 s; removes the "Engram at 4 bits" caveat. Decode 97.8 against 101.4 tok/s, inside the run-to-run range | yes |
| Fused FFN entry on the mxfp4 kernel (`DSV41_TP_FFNIN=3` declined with "why 8" before; patch in `tpFfnFused`) | decode 97.8 to 102.0; plain 77.3 to 82.0 (+6%); 1 stream 88-90 to 92-94; 2-8 streams unchanged | yes |
| `DSV41_TP_SUM=bf16` (existing switch, untried; suggested by a GPT Astra source review): steps of 7-16 rows send half the bytes between the Studios | 8 streams 172.7 to 177.3 (+3%), 4 streams 150.1 to 152.7 (+2%), 1-2 streams and decode unchanged; quality 48/48 | yes |
| `DSV41_FP4_PAIRED=1` (new, same review): mxfp4 experts take the paired gate/up prompt-reading kernel | engaged (`paired SwiGLU engaged`), quality 48/48, cold 26.8k prompt 7.40 s against 7.43 s: no gain | no (off by default) |
| `DSV41_TP_SPAN_SUM=4` (new): one cross-machine sum per 4 attention spans in prompt reading, in place of one per span | cold 26.8k prompt 7.78-7.79 s against 7.40-7.43 s: 5% slower (the per-span sums overlap GPU work); quality 48/48 | no (off by default) |
| `DSV41_TP_WIDE_SORT=7` (new): steps of 7-16 rows through the sorted prompt-reading kernels | 8 streams 159 against 177 (−10%); 1-4 streams unchanged; quality 48/48 | no (off by default) |
| DSpark cost ladder retuned to this pack's round times (`DSV41_SPARK_COST=0.92,1.06,0.167`) | 101.4 against 102.0 (18 runs against 9): no gain | no |

What is left after the fixes:

- **Against the same pair on 3.0bpw the big pack is still slower:** −10% / −3% / −7% / −9% at 1 / 2 / 4 / 8 streams (first pass), −7% on the decode bench, −6% plain.
- **4 and 8 streams moved only 2-3%.** Past 6 rows a step leaves the fused kernels. Two outside reviews (Gemini Neon, GPT Astra) both rank a separate wide mxfp4 kernel for 7-32 rows as the main remaining lever there, with an expected ceiling of about +6-10% at 8 streams; not built. The cheap version of that idea (reusing the sorted prompt-reading kernels for 7-16 rows) was tried and lost 10% at 8 streams.
- **Prompt reading:** both reviews point at the number of cross-machine sums per chunk (about 700 per 8,192 tokens) as the next thing to cut. Grouping them four at a time was tried and was 5% slower. One review notes the cold-prompt test does not purge the file cache; every run here used the same prompt text, so all compared figures had warm Engram rows.
- **Two users:** about 61 tok/s each on the big-pack pair, against 77-80 each on two separate 3.0bpw copies. Structural.
- **Cold prompt:** 8% later than one Studio, though now 4% sooner than the 3.0bpw pair (7.70 s).
- The stock build on the public pack reads the cold prompt in the same 7.4 s, which confirms the cold-prompt gain is the pack change, not the patches.

The sections below are the first measurements (pack `oQ4e-mtp` as downloaded, build `4eb3c7129077`), kept as the record.

## First result (before the fixes)

- **The pack:** `DeepSeek-V4.1-Flash-1017-oQ4e-mtp`. It holds the language weights at the precision the model was released in (4-bit experts, 8-bit trunk): 288 GiB in memory. One Studio's GPU limit is 232 GiB, so it cannot load on one. The pack on one Studio today, 3.0bpw, cuts the experts to 2-3 bits (209 GiB). One thing goes the other way: this pack stores the Engram lookup tables at 4 bits, while 3.0bpw keeps them as released.
- **It runs on the pair, and with our patches it is faster than the smaller pack on one Studio:**

| real prompts, 768-token answers, total tok/s | one Studio, 3.0bpw | pair, big pack, patched | change |
|---|---|---|---|
| 1 stream | 79.0 | 88.4 / 90.2 | **+12% / +14%** |
| 2 streams | 94.2 | 115.8 / 117.3 | **+23% / +25%** |
| 4 streams | 124.0 | 147.4 / 151.9 | **+19% / +22%** |
| 8 streams | not measured | 172.1 / 173.3 | |

(Two passes of each stream count; both are shown.)

- **Without the patches the big pack is slower than one Studio at 1 stream** (64.7 / 67.9 tok/s, −18% / −14%).
- **Quality check:** 48/48 on `quality.py` plain, `--par 4` and `--sys 9000`; no `begin▁of▁sentence` in any of the 144 answers.
- **No quality gain is measured here.** The check above only catches corruption. Whether released precision answers better than 3.0bpw needs a separate comparison.

## Stock against patched, same pack, same pair

| | stock v26.11.3 | PR #1146 + our earlier switches | + new `DSV41_FP4_NAX=1` | patched over stock |
|---|---|---|---|---|
| decode bench, DSpark, tok/s (9 runs) | 79.0 (72.6-87.6) | 83.1 (75.1-89.9) | **101.4** (96.6-107.0) | **+28%** |
| decode bench, plain (`--no-mtp`) | 62.9 | not run | **77.3** | **+23%** |
| 1 stream, real prompts | 64.7 / 67.9 | 70.7 / 82.6 | **88.4 / 90.2** | **+35%** |
| 2 streams | 97.2 / 99.6 | 98.3 / 101.1 | **115.8 / 117.3** | **+18%** |
| 4 streams | 132.8 / 134.1 | 132.8 / 132.2 | **147.4 / 151.9** | **+12%** |
| 8 streams | 169.0 / 170.5 | 171.7 / 172.6 | 172.1 / 173.3 | +2% |
| new question behind a shared 26,800-token system prompt | 8.6-8.8 s (nothing cached) | 0.26-0.27 s | 0.26-0.27 s | 97% sooner |

(Percent column: means of the two passes. The middle column's 1-stream passes differ by 17%, so read that cell loosely.)

- Nearly all of the decode gain comes from the new switch. The earlier switches add 5% on this pack because the two that mattered on 3.0bpw decline here: `DSV41_TP_NAXMOE` ("why 4": the NAX kernels take only 2-3 bit experts) and `DSV41_TP_FFNIN=3` ("why 8").
- The shared-prefix gain is `DSV41_TP_SLICE=1` from the earlier work: stock re-reads the whole system prompt for every new question under the split.
- At 8 streams the patches do nothing for this pack.

## Against one Studio on 3.0bpw

| | one Studio, 3.0bpw | pair, big pack, stock | pair, big pack, patched |
|---|---|---|---|
| decode bench, DSpark | 79.7 | 79.0 (−1%) | 101.4 (**+27%**) |
| decode bench, plain | 65.8 | 62.9 (−4%) | 77.3 (**+17%**) |
| 1 stream | 79.0 | 64.7 (−18%) | 88.4 (**+12%**) |
| 2 streams | 94.2 | 97.2 (+3%) | 115.8 (**+23%**) |
| 4 streams | 124.0 | 132.8 (+7%) | 147.4 (**+19%**) |
| cold 26,800-token prompt, time to first token | 6.89 s | 8.82 s (28% later) | 8.87 s (**29% later**) |
| follow-up on a cached prompt | 0.115-0.145 s | 0.10-0.11 s | 0.10-0.11 s |
| new question behind a shared system prompt | 0.30-0.31 s | 0.8 / 2.8 / 8.6 s at 2.3k / 8.9k / 26.8k | 0.24-0.27 s (about 15% sooner) |
| first chunk, short prompt | 0.146-0.162 s | 0.13-0.21 s | 0.14-0.22 s |

(Stream rows use the first pass; the one-Studio baseline is a single figure.)

## Losses and limits

- **Reading a long new prompt is 29% slower** than one Studio on 3.0bpw (8.87 s against 6.89 s at 26,800 tokens, about 3,020 prompt tok/s). The patches do not change it.
- **Against the same pair on 3.0bpw, the big pack is slower:** −13 / −5 / −9 / −11% at 1 / 2 / 4 / 8 streams (88.4 / 115.8 / 147.4 / 172.1 against 101.7 / 122.2 / 162.1 / 194.2), and −8% on the decode bench (101.4 against 109.9).
- **For two users who each want speed, two separate 3.0bpw copies win:** each Studio alone gives its user about 77-80 tok/s. On the big-pack pair two users get about 61 tok/s each (−22%). The pair's case is the larger pack, not parallel work.
- **First token on the decode bench rose** to 0.32 s mean with the new switch (0.17-0.43 s by run; 0.18-0.19 s without it). The real-prompt first chunk did not move.
- **Our build could not load this pack until we added a switch.** Rank 0 billed itself the whole 288 GiB and refused. Found afterwards, by reading the code: the cause is our own `DSV41_NO_BELL=1`. Without the bell connection the worker never answers rank 0's model check, which is where it reports its free memory, so rank 0 still sees 0 for the worker and bills the whole pack (`if (theirs == 0) return whole` in `distributed.zig`). Stock and PR #1146 builds use the bell and are not affected. `DSV41_TP_SHARE=1` is needed only together with `DSV41_NO_BELL=1`.
- The gather path (`[gather-nax] engaged`) still prints beside the fused mxfp4 line, so not every MoE step is on the fused kernel.
- Output wording is not identical between builds. At temperature 0 the patched plain output matches the stock plain output for the first 49-830 characters of each of the 9 bench runs, then drifts (likely a different summing order in the fused kernel). The two stock arms drift from each other in the same way (after 27-604 characters). Scores did not change.

## What was changed (both env-gated, off by default)

Patch: `bigpack/fp4-nax.diff` (about 160 lines, on top of the PR #1146 tree). Build hash `afab170a83d7` (first measurements: `4eb3c7129077`, without the fused FFN change).

1. **`DSV41_FP4_NAX=1`**: on an M5 the server built its fused mxfp4 MoE kernel only for GPUs without NAX, and the NAX kernels accept only 2-3 bit experts. A pack with 4-bit experts therefore had no fused MoE on this hardware. The switch builds the mxfp4 kernel on NAX GPUs too and uses it under the split, falling back per layer where it declines.
2. **`DSV41_TP_SHARE=1`**: bills rank 0 its share of a joined tensor split (half plus a tenth) before the worker has reported in. Needed only with `DSV41_NO_BELL=1`.

## Memory

- Rank 0's bill: 172.90 GB of a 232 GB limit. The worker reports 147,239 MiB held (143,020 on the stock build).
- With the model loaded, each Studio had about 155 GiB wired in total, so about 75 GiB is left under the GPU limit on each.
- Cached context is small on this model: about 3.2 KB a token, measured on the 3.0bpw pack with prompts up to 8,900 tokens (35 MB). By that figure a 200k-token project context is under 1 GB. **Not measured on this pack**, and no prompt over 27k tokens was run.

## What failed along the way

- Two launches of the patched build failed to load (the memory bill above): "needs ~300.17 GB, more than --max-resident-mem 232.00 GB", then `InsufficientMemory` at preflight with the cap raised. Both stopped cleanly. Fixed by `DSV41_TP_SHARE` (needed only because `DSV41_NO_BELL` skips the worker's memory report; see above).
- The first copy of the pack between the Studios went through SSH at 0.5 GB/s and was stopped. The cable copy tool did 293 GB in 130 s (2.25 GB/s); all 82 files then matched their SHA-256 names.
- A launcher fault held each run for 4 minutes after "ready" (a warm-up timer kept a pipe open). Fixed in our launcher.

## Not measured

- A retune of the DSpark cost ladder for this pack (`DSV41_SPARK_COST` is still the 3.0bpw tuning).
- The patched build's plain decode without the new switch.
- A 100k-token prompt.
- Any quality comparison between 3.0bpw and released precision.
- Another machine's numbers (a single 512 GB Mac) are not included.

## Switches used

Best switches: `DSV41_TP_NAXMOE=1 DSV41_TP_FFNIN=3 DSV41_TP_SUMSPLIT=1 DSV41_SPARK_COST=0.89,1.04,0.147 DSV41_NO_BELL=1 DSV41_TP_SLICE=1`.

