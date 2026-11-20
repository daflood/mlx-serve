# DeepSeek-V4.1-Flash split across two Mac Studios: can it decode faster than one?

> Lab notes from the measuring sessions, lightly edited for publication: machine names, paths and addresses are
> replaced, and the two Macs are called Mac 1 (rank 0) and Mac 2. Scripts named here that were tied to our machines
> (`arm.sh`, `pair.sh`, `package.sh`, `pair-big.sh`) and the raw `results/` and log folders are not in this branch.
> The benchmark and quality scripts are in `two-macs/scripts/`; the code is this branch's commits.

Status: updated 2026-11-20 09:55. Since 07:55: a daily-use launcher (`scripts/pair.sh`); an answer-quality check that found two bugs of mine (one switch withdrawn, one fixed; final settings score 48/48 alone, four at a time, and behind a shared system prompt, same as one Studio); multi-stream DSpark tests (no gain to be had); final stream figures re-measured; draft upstream reports in `upstream-drafts/` (not posted). Nothing of mine is running on either Studio. Mac 2 was rebooted at 08:16 (11 cluster launches since); Mac 1 is at about 33 since 06:36.

## TL;DR
**Yes. With a handful of small source patches, two Studios now decode faster than one in both modes, with max-effort thinking and DSpark working. The speed-up itself needed no sudo or password; the Thunderbolt Bridge fix further down needs one sudo install per Studio.**

| mode (512 tokens, effort max, temp 0) | one Studio | two Studios, best | ratio |
|---|---|---|---|
| plain decode (`--no-mtp`) | 65.8 tok/s | **87.1 tok/s** (87.0-87.2, 6 runs) | 1.32x |
| DSpark (the default) | 79.7 tok/s (74 / 79 / 87 by prompt) | **109.9 tok/s** (109 / 107 / 113; 9 runs) | 1.38x |

- Stock mlx-serve 26.11.3 on the pair is an exact tie with one Studio (65.5 tok/s plain). The published "pair is no faster" results are right for the shipped build.
- The main cause is in mlx-serve, not the network. On this pack and chip the split ran the MoE on a slow unfused path (Neon's review pointed at it; I confirmed it in the source). Using the fused kernels that one Mac uses took the pair from 65.5 to 77.2 tok/s (80.9 with the per-step bell also off).
- The network costs under 1 ms of a ~12 ms step. Replacing every collective with a fake one shortens the step by 0.9 ms on either build (stock + NAXMOE: 12.36 -> 11.5 ms; PR build + NAXMOE: 11.9 -> 11.0 ms).
- What limits the pair now is mostly each Mac's own step. One Studio running only its half of the split, with no network at all, takes 10.3 ms a step (the whole model takes 15.3 ms); the real pair takes 11.6 ms. In the solo run the decode thread is ~92% busy building the graph and encoding Metal commands, and the GPU is ~93% busy: both are near their limit, so no single fix gives a big jump (see "Where a pair step goes"). The remaining ~1.1 ms is the sums; for plain decode the control channel turned out not to matter.
- The control channel matters for DSpark and not for plain decode. Moving it from an ssh tunnel on the LAN to the cable took DSpark from 104.9 to 108.2, and dropping the TCP wake-up ("bell") so the worker waits on RDMA took it to 109.9. Plain decode stayed at 87.0-87.1 through both.
- DSpark's draft policy is tuned for one Mac. Giving it the pair's measured round costs added ~2% (102.7 -> 104.4 and 104.9 in two launches).
- Nothing was posted upstream. The changes are this branch's commits.

Caveats
- The bench is 3 long prompts x 2-3 repeats of 512 tokens. Plain-decode runs repeat within 0.3%; DSpark varies by prompt and by run (one Studio: 77.1 in one launch, 79.7 in another).
- Pair output is not bit-identical to one Mac. It diverges from the one-Mac text at the same points the stock pair does (the two halves are summed in bf16). All outputs read as normal reasoning text. I did not score answer quality.
- Mac 2 rebooted at 01:40 and lost its cable IPv4 addresses. Until 05:40 I worked around it in software (patch 4 below) with the control connection in an ssh tunnel over the LAN; rows marked "cable" are after the addresses were restored.

## Real-world use (added 2026-11-20, 07:55)
The questions were time to first token, concurrent streams and prompt length, with every figure shown against one Studio. Bench: `scripts/rw_bench.py` (varied prompts, effort max, temperature 0); raw rows in `results/rw.jsonl`; summary with `python3 scripts/rw_summ.py results/rw.jsonl <label>`. One Studio = the PR build started with `--model` (the 26,800-token row is the stock build, 07:15); pair = the best decode config plus the two new switches below, joined through the loopback tunnel.

| what a user feels | one Studio | two Studios | pair vs one |
|---|---|---|---|
| decode speed, one stream, DSpark | 79.7 tok/s | 109.9 tok/s | **+38%** |
| decode speed, one stream, plain | 65.8 tok/s | 87.1 tok/s | **+32%** |
| short question: first chunk (4 questions) | 0.15-0.27 s | 0.12-0.23 s | 12-22% sooner |
| short question: first word of the answer (effort low) | 0.72-1.95 s | 0.58-1.21 s | 12-56% sooner |
| follow-up turn in a cached conversation (2k-27k tokens) | 0.115-0.145 s | 0.088-0.103 s | 20-30% sooner |
| new question on a shared 2,250-token system prompt | 0.29 s | 0.22 s (was 0.76 s before the fix) | **25% sooner** (was 2.6x later) |
| new question on a shared 8,900-token system prompt | 0.30 s | 0.22 s, one of four at 0.54 s (was 2.55 s before the fix) | **26% sooner** (was 8.5x later) |
| two conversations taking turns (later turns) | 0.10-0.11 s | 0.08 s typical, 0.31-0.58 s on 3 of 8 | 20-25% sooner; the 3 slow turns were the new build's one-time self-warm-up requests (`warm_requests.zig`, 256-token prompts it serves itself when idle) landing in front of them, not the cache |
| cold 2,300-token prompt | 0.83-0.91 s | 0.74-0.78 s | 10-15% sooner |
| cold 8,900-token prompt | 2.48-2.53 s | 2.52-2.62 s (one at 2.88 s) | 2-4% later |
| cold 26,800-token prompt | 6.89 s | 7.70 s | 12% later |

Concurrent streams (each a different ~100-token prompt, 256 tokens out, started together):

| streams | one Studio: total / per stream | pair: total / per stream | pair vs one (total) | median TTFT one / pair |
|---|---|---|---|---|
| 1 | 72 / 77 tok/s | 88 / 93 | +23% | 0.27 / 0.15 s |
| 2 | 90 / 52 | 116 / 65 | +29% | 0.31 / 0.22 s |
| 3 | 103 / 38 | 138 / 50 | +34% | 0.51 / 0.31 s |
| 4 | 106 / 29 | 151 / 41 | +42% | 0.56 / 0.39 s |
| 6 | 130 / 24 | 168 / 30 | +29% | 0.84 / 0.55 s |
| 8 | 140 / 20 | 174 / 24 | +24% | 1.04 / 0.76 s |
| 12 | 152 / 14 | 191 / 17 | +26% | 1.51 / 1.07 s |
| 16 | 164 / 11 | 205 / 14 | +25% | 2.02 / 1.46 s |

**Rows 1-6 of the pair column were measured with `DSV41_TP_BATCHFUSED=1`, which was later found to corrupt output (see "What changed", item 3); the valid pair figures for 1-8 streams are in the 09:50 table further down.** Rows 8-16 are from the earlier run without it (the switch only serves up to 6 rows in a step). Total throughput peaks at 16 streams on both and falls at 24 (157 / 196). No request was refused up to 24.

### Rerun after the Thunderbolt Bridge fix (08:00, same launch settings on both sides, long-prompt warm-up on both)
The bridge fix was installed on both Studios at about 07:55; the packet flood is gone. One run each (`rw2-single`, `rw2-pair`).

| what a user feels | one Studio | two Studios | pair vs one |
|---|---|---|---|
| short question: first chunk (4 questions) | 0.146-0.162 s | 0.108-0.136 s | 16-26% sooner |
| short question: first word of the answer | 0.63-0.99 s | 0.53-0.79 s | 15-33% sooner |
| follow-up turn in a cached conversation | 0.112-0.115 s | 0.087-0.089 s | 22-23% sooner |
| new question on a shared 2,250-token system prompt | 0.29-0.30 s | 0.21-0.22 s | 26% sooner |
| new question on a shared 8,900-token system prompt | 0.30-0.31 s | 0.22-0.23 s | 27% sooner |
| cold 2,300-token prompt | 0.81-0.85 s | 0.72-0.75 s | 11-13% sooner |
| cold 8,900-token prompt | 2.47-2.61 s | 2.47-2.48 s | 0-5% sooner |
| 1 stream: total / per stream | 73 / 77 tok/s | 91 / 95 | +24% |
| 2 streams | 90 / 51 | 120 / 64 | +33% |
| 4 streams | 117 / 32 | 156 / 43 | +34% |
| 8 streams | 141 / 19 | 184 / 26 | +30% |

The pair gained a little from the fix (prompt reading at 8,900 tokens went from 3,460 to 3,600 tok/s, 8 streams from 174 to 184 tok/s); one Studio moved about as much at 4 streams (106 to 117). The 26,800-token cold prompt was not rerun.

Fake-sum pair on long prompts (timing only, output is garbage): 4,083 tok/s at 8,900 tokens and 4,288 at 26,800 (6.25 s), against 3,600 and about 3,480 (7.70 s) with real sums and 3,430-3,890 on one Studio. So the sums cost about 1.4 s of a 26,800-token prompt, and removing all of them would make the pair about 10% faster than one Studio at that length. That is the most this design can give for a brand-new long prompt.

Cache capacity check (one Studio, 08:06): 24 different 2,300-token conversations opened in a row, then each revisited. All 24 were still cached with the default cache (32 entries, 2 GB) and with a larger one (512 entries, 16 GB); follow-up TTFT 0.099 s median in both. The default is enough at this scale.

### What changed for real-world use
1. **Shared-prefix cache reuse now works on the pair (`DSV41_TP_SLICE=1`).** One Studio restores the shared front of a cached prompt (same system prompt, new question; an edited or regenerated turn). Under the split that was switched off (`sliceSnap` returned null for a tensor split), so every such request read the whole prompt again: 2.55 s instead of 0.30 s on an 8,900-token system prompt. This is the common "cold prompt" in real use. The patch has rank 0 slice its snapshot and tell the worker to slice its copy (`SnapOp.slice`), then replays the last 128-token window on both ranks (the step header carries a replay flag). Result: 8,876 of 8,893 tokens come from the cache and the first token arrives in 0.22 s. The first question's text is identical with and without the switch; later answers differ in wording as they do on one Studio (the replayed window is approximate by design).
2. **A long-prompt warm-up at start (`WARMWIDE=1` in `scripts/arm.sh`).** The first long prompt after any launch was slow on the pair and on one Studio (pair: 1.74 s / 4.78 s for 2.3k / 8.9k tokens against 0.78 s / 2.59 s later; one Studio: 1.07 s / 3.67 s against 0.90 s / 2.53 s). It happens per launch, not only after a reboot. Three varied prompts of about 700, 2,600 and 9,100 tokens at start take 6 s and remove it.
3. **Withdrawn: multi-stream decode on the fused kernels (`DSV41_TP_BATCHFUSED=1`). It corrupts output; leave it off.** With 4 requests at once, 22 of 48 answers had stray `<｜begin▁of▁sentence｜>` tokens in the thinking text and 2 of 48 answers were wrong; with the switch off the same test is 48/48 and clean, as is one Studio (`results/quality2.jsonl`, labels `q-pair-par4`, `q-pair-par4-nobf`, `q-single-par4` in `results/quality.jsonl`). My earlier text check ("coherent and on topic") missed it. Its measured gain (+5% / 0 / +10% / +3% at 2 / 3 / 4 / 6 streams, one run each) was inside the run-to-run spread anyway. The switch is still in the build, off by default, and `scripts/pair.sh` no longer sets it. I did not find the bug.
4. **Joining through a loopback tunnel (`TUN=1 CABLE=1`).** Mac 1's firewall (on, stealth) most likely closed the worker's connection to the coordinator in 4 of 5 launches between 07:25 and 07:40: the worker saw the connection accepted and then closed, and rank 0 never saw it. A bare `dist-probe` from an ssh shell joined fine in between. `socketfilterfw --listapps` on Mac 1 has an allow rule for the stock build's binary path and none for the PR build's, so Mac 1's screen may be showing an "accept incoming connections?" prompt for it. With the coordinator on loopback through `ssh -L` the join worked 2 times of 2. RDMA data still uses the cable.

### What did not help
- **Prompt reading (cold prefill) is not faster on the pair, and two cheap fixes did not change that.** One Studio running only its half of the model reads a 26,758-token prompt at 4,555 tok/s against 3,891 for the whole model, so the split divides only about 30% of prefill work. The pair then pays for 700 sums per 8,192-token chunk (3.4 GB) and reads at 3,480-3,520 tok/s. A second Thunderbolt cable (both reviewers' first suggestion) halved a 26 MB round trip (5.66 -> 2.96 ms) and left prefill unchanged (3,470 / 3,517 tok/s). Splitting the wide MoE sum into overlapped 2,048-row groups (`DSV41_TP_MOE_ROWS=2048`) made it slower (3,246 tok/s). The half-model figure is the ceiling for the current design: about 17% faster than one Studio if the sums cost nothing. Going past that ceiling needs the row-wise work (projections, indexer, mixes) divided between the Macs by rows, which is a redesign. The 2,048-row test also shrank the MoE groups, so it does not rule out other ways of overlapping the sums.
- **DSpark with two or more streams cannot be made faster by retuning; I tested it (08:30-08:45).** With company, a stream drafts on about 5% of its rounds. Measured on the pair: a round of 2 / 3 / 4 streams costs 15.8 / 18.9 / 23.2 ms, each extra verify row 2.5-3.7 ms, more than 6 rows another ~2.5 ms, and one draft 3.6-4.1 ms. At 2 streams a plain token costs 7.9 ms; a drafted one costs a row plus its share of the draft, and 70-95% of first drafts are accepted, so it comes out even. Two runs each, 768 tokens a stream: default 123.5 / 124.1 tok/s total at 2 streams; cost model set to the measured values (`DSV41_GROUP_COST=8.4,3.7,2.7,2.5`) 122.3 / 123.5; drafting forced on every round (`DSV41_GROUP_DRAFT=2`) 124.3 / 125.4. All within run-to-run spread, so the shipped back-off is right and I left the defaults. Both switches stay in the build, off.
- **The fused decode path past 6 rows is not worth building.** `max_rows = 6` is baked into the kernels in 94 places, and two 4-row fused batches cost about 47 ms against 39 ms for the unfused path at 8 rows.
- **For exactly two users, one full copy of the model on each Studio would give each about 77-80 tok/s** against 65 on the pair (Astra's suggestion). That needs the conversations kept on their own Studio and gives up the 110 tok/s single-stream speed. The pair is better at 1 stream and at 3 or more.

### Added 08:20-09:55: launcher, quality check, two bugs, final stream figures
- **Daily-use launcher: `scripts/pair.sh start | stop | status`** (run from the MacBook). It checks both builds match and both cable addresses are up, starts rank 0 on Mac 1 and a retrying worker on Mac 2 through the loopback tunnel, loads the model and runs the long-prompt warm-up (bounded at 4 minutes). About 80 seconds to "ready". The API is `http://127.0.0.1:11240/v1` on Mac 1; `BIND=0.0.0.0` exposes it on Mac 1's network addresses (no API key unless you add `--api-key` through `FLAGS`). It started cleanly 10 times of 11. `scripts/watch.sh <command>` runs a test against the live pair and aborts within about 6 seconds if either process is gone.
- **The one failed start: the first after Mac 2's reboot.** The worker died in the 842-token warm-up prompt with Metal `Insufficient Memory`, and rank 0 waited in a sum until I stopped it; both GPUs went back to 0% and no reboot was needed. Nothing else held memory on Mac 2 (Splash had started at login but was idle at 100 MB; 237 GB free). That start also bound the API to the hostname instead of loopback (a `HOST` variable bug in the script, fixed since), so the settings were not identical. Cause unknown; seen once.
- **Answer quality: the first check passed, a wider one found two bugs.** `scripts/quality.py`: 48 questions with checkable answers (arithmetic, logic, code output, facts), effort low, temperature 0; `--par N` sends N at a time, `--sys N` puts every question behind one shared system prompt of about N tokens. One at a time the pair scored 48/48, as one Studio does. Then:
  - Four at a time with `DSV41_TP_BATCHFUSED=1`: 46/48, and 22 of 48 answers had stray tokens in the thinking text. With the switch off: 48/48, clean. **Switch withdrawn** (item 3 above).
  - Behind a shared 10,000-token system prompt, the second request killed the worker (`DistPeerDiverged`) on some launches and not others. Cause: my `DSV41_TP_SLICE` patch packed the snapshot id and the cut length into one 64-bit value, and the id counter (`tp_snaps`) is never initialised in the upstream code, so on some launches the ids are huge and the length arrived garbled. **Fixed** (the length now travels as its own `SnapOp.cut` message; commit 75537015, build `61d9d9b1e3ad`). The uninitialised counter is an upstream bug worth reporting.
  - Final settings, one launch: four at a time 48/48, shared system prompt 48/48 (96 restores from a cut snapshot), both together 48/48, all clean (`results/quality2.jsonl`, labels ending `-h`). One Studio four at a time: 48/48.
- **Final stream figures (09:50, final settings, 768 tokens a stream, two runs; one Studio one run, same build):**

| streams | one Studio, total tok/s | pair, total tok/s | pair vs one Studio |
|---|---|---|---|
| 1 | 79.0 | 101.7 / 102.0 | +29% |
| 2 | 94.2 | 122.2 / 123.1 | +30% |
| 3 | 111.7 | 147.9 / 149.4 | +33% |
| 4 | 124.0 | 162.1 / 162.9 | +31% |
| 8 | not measured at 768 tokens | 194.2 / 196.4 | (about +30% at 256 tokens, table above) |

  The single-stream gain here (+29%) is below the headline +38% because the headline is the 512-token, three-prompt decode bench; this is a different prompt and length and includes time to first token in the total.
- **First-token times on the final build, same launch:** first chunk 0.110-0.115 s (one Studio 0.146-0.162 s, 21-32% sooner); a new question behind a shared system prompt 0.21 / 0.22 / 0.23-0.24 s at 2,300 / 8,900 / 26,800 tokens (one Studio 0.30-0.31 s at 8,900: 27% sooner; the 26,800 case was not measured on one Studio); cold 26,800-token prompt 7.39 s (one Studio 6.89 s: 7% later).

### Thunderbolt Bridge packet loop (found 07:30, fixed 07:55)
Both cable ports on each Studio are members of macOS's `bridge0`, so the two cables form a loop. Each Studio receives about 200,000 packets a second on each cable port, and `mDNSResponder` and `netbiosd` each use about a core on both Macs. It started between 06:38 (Mac 2 logged an mDNSResponder CPU report then, two minutes after Mac 1 rebooted) and about 07:00 by the packet counters (roughly 630 million packets on each bridge at ~300,000 a second is about 35 minutes), which is about when Mac 1's cable addresses came back after its reboot. So the decode tables (before 06:30) were measured without it, and most of the real-world tables with it, on the one-Studio side and the pair side alike. Single-stream decode after 07:00 (108-112 tok/s) matches the earlier 109.9, so I expect the fix to change little there; TTFT and the concurrency rows are worth one more run afterwards. The startup item that sets the cable addresses now also removes the cable ports from the bridge. After installing, check that the cable addresses are present, the RDMA ports are still ACTIVE and the packet rate has dropped before any pair run.

## Results
All arms: `--ctx-size 65536`, 3 prompts (~100 prompt tokens each), 512 completion tokens, `reasoning_effort: max`, temperature 0. tok/s is the server's `predicted_per_second`, mean over all requests (min-max). TTFT is the client's time to the first streamed chunk, median.

| arm | build + env | tok/s | TTFT | step period |
|---|---|---|---|---|
| single-plain | stock, `--model` at start | 65.5 (65.4-65.6) | 0.27 s | 15.3 ms |
| singleh-plain | stock, started headless like the pair | 65.8 (65.4-66.2) | 0.21 s | |
| single-dspark | stock | 77.1 (63.0-88.7) | 0.22 s | |
| singleh-dspark (9 runs) | stock, headless | 79.7 (70.3-88.5) | 0.22 s | |
| pair-stock-plain | stock | 65.5 (65.3-65.6) | 0.26 s | 15.25 ms |
| pair-nax-plain | stock, `DSV41_TP_NAXMOE=1`, bell via ssh | 77.2 (76.9-77.4) | 0.15 s | 12.9 ms |
| pair-nax-plain-nobell | same, worker busy-waits | 80.9 (80.8-81.0) | 0.15 s | 12.36 ms |
| pair-ffn2-plain | + `DSV41_TP_FFNIN=2` | 82.3 (82.2-82.4) | 0.20 s | 12.14 ms |
| pair-pr-nax-plain | PR #1146 + NAXMOE, no bell | 83.0 (82.9-83.1) | 0.26 s | 12.0 ms |
| pair-pr-nax-plain-pipe (2 launches) | PR #1146 + NAXMOE, bell via ssh, piped step on | 83.7 / 83.8 (83.5-84.0) | 0.16-0.29 s | 11.9 ms |
| **pair-pr-ffn3-plain-pipe** (6 runs) | PR #1146 + NAXMOE + `DSV41_TP_FFNIN=3`, bell via ssh | **86.9** (86.8-87.0) | 0.26 s | 11.58 ms |
| pair-pr-fakesum-pipe | PR #1146 + NAXMOE + fake sums (timing only) | 91.2 (89.3-92.2) | 0.14 s | 11.0 ms |
| pair-nax-fakesum | NAXMOE + fake sums (timing only, wrong output) | 86.8 (86.3-87.4) | 0.14 s | 11.5 ms |
| pair-ffn1-plain | `DSV41_TP_FFNIN=1` (sums of 41-51 KB) | 38.4 | 0.21 s | 27 ms |
| pair-nax-dspark (9 runs) | stock + NAXMOE, no bell, DSpark | 95.2 (74.2-109.3) | 0.16 s | |
| pair-pr-ffn2-dspark-pipe (9 runs) | PR #1146 + NAXMOE + FFNIN=2, DSpark | 98.9 (92.9-104.6) | 0.31 s | |
| pair-pr-ffn2-split-dspark-pipe (9 runs) | + `DSV41_TP_SUMSPLIT=1` | 101.2 (93.4-105.5) | 0.36 s | |
| pair-pr-ffn3-split-dspark-pipe (9 runs) | PR #1146 + NAXMOE + FFNIN=3 + SUMSPLIT | 102.7 (95.0-106.8) | 0.15 s | |
| pair-spark-costB (6 runs) | + `DSV41_SPARK_COST=0.89,1.04,0.147` | 104.4 (103.4-106.6) | 0.22 s | |
| **pair-best-dspark** (9 runs, second launch of the same) | same | **104.9** (98.3-110.8) | 0.16 s | |
| pair-cable-plain (6 runs) | plain best config, coordinator + bell on the cable, stock libjaccl | 87.0 (86.6-87.3) | 0.15 s | 11.45 ms |
| **pair-cable-nobell-plain** (6 runs) | same + `DSV41_NO_BELL=1` | **87.1** (87.0-87.2) | 0.15 s | |
| pair-cable-dspark (9 runs) | DSpark best config, coordinator + bell on the cable | 108.2 (101.5-114.9) | 0.16 s | |
| **pair-cable-nobell-dspark** (9 runs) | same + `DSV41_NO_BELL=1` | **109.9** (103.3-117.7) | 0.23 s | |
| pair-spark-costA (6 runs) | cost ladder from the true 11.5 ms plain step | 95.4 (94.4-96.8) | 0.19 s | |
| pair-spark-pin6 (6 runs) | always verify 6 rows | 93.5 (85.1-113.8) | 0.15 s | |
| singleh-pr-dspark (6 runs) | PR #1146 build, one Studio, DSpark | 77.7 (69.6-88.8) | 0.21 s | |
| singleh-pr-plain | PR #1146 build, one Studio | 66.2 (66.2-66.3) | 0.26 s | |
| single-plain-bigbuf | stock, `MLX_MAX_MB_PER_BUFFER=1000000` | 64.8 | 0.32 s | |

- TTFT is 0.14-0.36 s on every arm; the pair is not worse. Prompt processing is faster on the pair: ~685 prompt tok/s against ~480 on one Studio (short prompts only).
- No arm logged a declined fused path on either rank, and DSpark acceptance on the pair looks like one Studio's (0.82-1.32 extra tokens a round).

Per-collective cost
- No model, CPU-side, back to back: 21 us for a 20 KB bf16 all_sum (both cables, and the same with link-local GIDs).
- Inside a GPU graph with fast sync (probe `--chain`): ~27 us each, so 80 of them would be ~2.2 ms.
- In the real decode step: real sums against fake sums differ by 0.85 ms a step, about 11 us per collective.
- A sum of 41 KB or 51 KB inside the graph is far slower (pair-ffn1-plain: +15 ms a step with both GPUs mostly idle). I did not find why; CPU-side the probe shows bigger messages are fine. Keeping every decode sum under 32 KB avoids it.

## What I changed
All env-gated and off by default. Both ranks must set them alike.

1. **`DSV41_TP_NAXMOE=1`: fused MoE under the split** (`deepseek_v41.zig`, `moeFused`). Under `--dist tensor` only the mxfp4 MoE kernel was wired up. This pack on an M5 Ultra uses the NAX affine kernels (`moe_up` / `moe_down`), so the split fell back to an unfused routed-gather path with f32 sums. The patch runs the NAX kernels on each rank's half of the units, so the output is that rank's part of the MoE. Worth 65.5 -> 80.9 tok/s.
2. **`DSV41_TP_FFNIN=2`: fused FFN entry under the split** (`tpFfnFused`). One Mac runs wo_b, the hyper-connection expand, the mixes, the norm and the router in two launches; the split ran them as generic ops. The patch uses the same two launches around the attention sum. Worth ~1.5% (80.9 -> 82.3).
   - Mode 1 sums the expanded streams instead and needs no generic ops at all. Its math is right but its sums are 41-51 KB and it runs at half speed. Not usable as is.
   - **Mode 3 (`DSV41_TP_FFNIN=3`)** adds one new Metal kernel (`tpMix`) that does the hyper-connection mix, the bf16 rounding and the next norm's input in one launch around each sum, replacing ~16 small generic ops per layer. Text is identical to mode 2 on the solo rig, where it is worth 4% over mode 2 (92.7 -> 96.8). On the pair, the PR build went from 83.8 without the FFN patch to 86.9 with mode 3 (+3.7%, modes 2 and 3 together; I did not run mode 2 plain on the PR build). This is the mode to use.
3. **`DSV41_TP_SUMSPLIT=1`: keep decode sums under 32 KB** (`tpSum`). A 4-6 row DSpark verify sum goes as two. Worth ~2% on DSpark (98.9 -> 101.2; one launch each, so treat it as a hint).
4. **`JACCL_GID_LL=1`: RDMA without an IPv4 address on the cable** (MLX `jaccl/rdma.cpp`). JACCL insists on an IPv4-mapped GID. The patch uses the port's link-local GID. Same latency. This is what let the pair run after Mac 2's reboot without a password.
5. **`DSV41_SPARK_COST=c1,a,b`: DSpark round costs for the pair** (`spec/dspark.zig`, PR build only). DSpark picks how many rows to verify from a fixed cost ladder scaled by a plain-step estimate. On the pair that estimate never updates (it stays at the 17.7 ms prior; the real step is 11.5 ms) and the ladder's shape is one Mac's. Measured pair rounds: 15.8 / 18.4-18.7 / 21.0 / 23.6 / 26.9 / 28-29 ms for 1-6 rows. `0.89,1.04,0.147` writes that ladder in units of the prior. Worth ~2%. `DSV41_SPARK_PLAIN_MS` and `DSV41_SPARK_PIN` are diagnostic levers; the log line `[xt] dspark rounds by rows` prints the measured ladder.
6. **`DSV41_NO_BELL=1`** (PR build, `cluster/distributed.zig`): the worker does not dial the bell and waits on the RDMA link instead (one core busy). A control message then never waits for a TCP byte to cross; the piped step is off without the bell, which costs nothing measurable. Worth +1.6% on DSpark over the cable bell.
7. Diagnostic levers, off by default: `DSV41_DUMMY=n` (2n extra tiny GPU launches a layer), `DSV41_TP_SOLO=r/n` (one Mac runs one rank's share with fake sums), `DSV41_EVAL_EVERY=N`, `DSV41_NO_GPU_DECODE=1`, and `MLX_EVAL_COUNT=1` (a primitive and per-kernel histogram in MLX's `transforms.cpp`; it lives in the variant library `lib/mlx-count`, selected with `XLIB=mlx-count`, not in the shipped libmlx).
8. Timers and counters (`[xt]` log lines), a fake-sum lever (`DSV41_TP_FAKESUM`), and launch scripts.

PR #1146 (open upstream, head add11dd9) adds a split LM head, a sharded DSpark draft and a piped decode step. On top of patch 1 it is worth ~3% plain and ~4% DSpark. The best numbers above are on the PR build.

## What worked and what didn't
Worked
- Fused NAX MoE under the split: the win.
- Fused FFN entry with one kernel for the glue around each sum (FFNIN=3): +3.7% on the pair.
- DSpark round costs measured on the pair: +2%.
- Dropping the per-step TCP "bell" so the worker busy-waits on RDMA: 77.2 -> 80.9. The bell rode an ssh tunnel here; on the cable it would cost less.
- PR #1146's split head and sharded draft.
- Link-local GIDs for JACCL.

Didn't work, or didn't matter
- **The network.** ~0.85 ms of a 12 ms step.
- **PR #1146's piped step.** It engages on every step (counted 256 of 256), but the step period stays ~11.9 ms. The pipe overlaps the token read-back with the next step's encoding, but the step is bound by host encoding and the GPU, not by that read-back (see "Where a pair step goes"; forcing the read-back every step costs one Studio nothing). I first blamed MLX's 10-task limit (`MAX_ACTIVE_TASKS`); I have no stack evidence for that, and Astra's review says the same.
- **Fewer GPU command-buffer commits** (`MLX_MAX_MB_PER_BUFFER`): no change on one Studio (64.8 vs 65.5).
- **Committing right after each fence** (`MLX_FENCE_COMMIT`, MacBook only): no gain.
- **Summing bigger tensors to skip generic ops** (FFNIN mode 1): half speed.
- **Replicated attention** (one sum per layer): rejected on paper. Attention is 6.6 of the 12.1 GB read per token in this pack.
- **The control channel, for plain decode.** Cable or ssh tunnel, bell or no bell: 86.9-87.1.
- **Cheaper kernel launches in MLX** (`patches/mlx-kernel-shared-NO-GAIN.diff`: a launch shares the generated source and the compiled pipeline instead of copying one and looking the other up): 96.7 against 97.2 on the one-Studio rig. No gain.
- **Fewer launches.** Adding 4 and 12 dummy GPU launches a layer (`DSV41_DUMMY`) costs 1.9 us each (10.34 -> 10.65 -> 11.26 ms). The ~17 launches a layer are not what the step is made of; the time is inside the big kernels.
- **An uneven split.** In the pair, rank 0's GPU reads ~93% busy and the worker's ~64-75%, which looked like an imbalance. It is not: rank 1's half alone runs at 94.3 tok/s and rank 0's at 96.7. A profile of both ranks in a live pair shows both decode threads ~80% busy; rank 0 waits ~2 ms a step for its own GPU and the worker waits ~2 ms for the next step's message.
- **DSpark with the "true" plain step** (costA) or **always 6 rows** (pin6): 95.4 and 93.5, both worse than the default's 102.7. With the true step the policy's backoff stops drafting too often.
- (Explained at 05:50, see Operational findings.) **Rank 0 on Mac 2 with the worker dialling the LAN directly** (to drop the ssh tunnel's ~0.4 ms per control message): the worker's JACCL connect timed out (error 60) although `nc` and a plain C client connect in under 1 ms both ways. The cause was the ssh-session rule below, not JACCL.
- Apple's `ibv_uc_pingpong` fails on these cables although JACCL works.

Operational findings
- A `--dist` server started with `--model` exits (`DistWorkerNotJoined`) before a worker can join. Start it with `--model-dir` only, let the worker join, then send a first request.
- Mac 1's firewall (stealth mode) drops the worker's dial on the LAN address about two times in three on the first night, and 4 of 5 launches after 07:25. Loopback through an ssh tunnel is reliable.
- **A rank started over ssh must keep that ssh session open if it dials a non-loopback address.** macOS blocks local-network connects from a process whose ssh session has ended: JACCL's connect then fails with error 60 while `nc` from a live session works. This is what I had blamed on the firewall. `scripts/arm.sh` now keeps the session open (`ssh -f ... ; sleep`). Under launchd or a login session it does not arise.
- Do not test the coordinator port with `nc`: rank 0 accepts exactly one connection and the probe uses it up.
- `/usr/bin/nohup` and `/usr/bin/timeout` strip `DYLD_LIBRARY_PATH`. Pass it through `env` after them.
- No hang (#1237) in ~40 pair launches, and no `Couldn't allocate protection domain`. Mac 1 has done roughly 55 JACCL inits since its last reboot, of the ~60 mlx #3207 warns about.

## Where a pair step goes
Measured 03:10-03:50 on one Studio with a rig I added (`DSV41_TP_SOLO=0/2`): it loads rank 0's half of the split, fakes the sums, and needs no second Mac, so it costs no pair launches.

| one Studio, plain decode | tok/s | step |
|---|---|---|
| whole model | 65.8 | 15.2 ms |
| whole model, token synced to the host every step (`DSV41_NO_GPU_DECODE=1`) | 65.7 | 15.2 ms |
| half the split alone (NAXMOE + FFNIN=2) | 92.7 | 10.8 ms |
| half the split alone, FFNIN=3 (new mix kernel) | 96.8 | 10.3 ms |
| a quarter of the split alone (falls back to unfused MoE) | 89.7 | 11.1 ms |
| half, one eval per step instead of one per layer (`DSV41_EVAL_EVERY=40`) | 81.1 | 12.3 ms |
| half, eval every 4 layers | 93.2 | 10.7 ms |
| piped pair with fake sums (two Studios, PR build) | 91.2 | 11.0 ms |

- **The half model alone takes 10.8 ms.** That is the pair's ceiling before any network cost, and it matches the pair's fake-sum step. So the "7 ms that does not shrink" is inside each rank.
- **It is host-bound.** A `sample` of the solo process shows the decode thread ~92% on the CPU: ~67% inside `mlx_async_eval` (MLX's eval loop, Metal command encoding, buffer allocation), ~25% building the graph in Zig, and only ~7% waiting for the GPU. `runLayers` hands the graph over once per layer, 40 times a step.
- **The GPU is nearly full too.** The busy gauge reads 93% on the solo half (no fences there, so the gauge can be trusted), the same as on the whole model. So the GPU needs roughly 9.5 ms for half the weights against 14 ms for all of them: halving the weights cut GPU time by a third, not a half. The quarter run says the same.
- A decode step encodes about 10.6 custom kernels per layer under the split (8.4 on one Mac), ~420 a step, at roughly 24 us of host time each. The split path also encoded ~28 small generic ops per layer (reshape, cast, slice, broadcast) against ~7 on one Mac. Folding the ones around the sums into one kernel (`DSV41_TP_FFNIN=3`) took them to ~12 and gave 4%.
- Syncing the token to the host every step costs one Studio nothing, so the missing piped step is not the problem. Evaluating less often does not help either.
- Because both the host thread and the GPU are near their limit at ~10 ms, moving the encoding to a second thread would gain a few percent at most. I did not build it.
- The network: real sums against fake sums differ by 0.85 ms a step on the stock build. That number sits behind the host-bound step; it would matter more if the step got shorter.

### Which decode kernels cost the most (half-model rig, 04:10-06:00)
One Studio running its half of the split (10.35 ms a step), with one kernel at a time launched twice per layer (`MLX_KERNEL_DUP=<name>` in the `mlx-count` library variant, `scripts/dup_sweep.sh`, raw in `logs/dup-sweep.txt`). The added time is roughly that kernel's cost across the layers:

| kernel | added ms a step |
|---|---|
| moe_up | +1.17 |
| moe_down | +0.99 |
| wo_a | +0.86 |
| attn | +0.79 |
| ffn_in_post | +0.76 |
| tp_mix (2 launches a layer) | +0.41 |
| wq_b | +0.38 |
| in_proj, ffn_in (first launch) | 0 measured; the duplicate was probably never evaluated |

No kernel dominates: the two MoE kernels are about a fifth of the step and the rest is spread evenly, which is why no single kernel fix gave a jump.

## Where a DSpark round goes
The PR build logs the mean round time by the number of rows verified (`[xt] dspark rounds by rows`):

| rows verified | one Studio | pair (best config) |
|---|---|---|
| plain step, no draft | 15.2 ms | 11.6 ms |
| 1 (draft only, nothing to verify beyond the next token) | 19.0 ms | 15.6-15.8 ms |
| 2 | 22.5 ms | 18.4-18.7 ms |
| 3 | 26.0 ms | 21.0-21.2 ms |
| 4 | 29.1 ms | 23.6 ms |
| 5 | 33.6 ms | 26.9 ms |
| 6 | | 28-29 ms |

- **The draft is not faster on the pair**: ~4.2 ms against ~3.8 ms on one Studio (~3.5 ms with the control channel on the cable and no bell; the table's pair column is from the tunnel runs, each row is ~0.6-0.9 ms shorter now). It is a chain of small kernels plus five in-graph gathers, so it is host-bound like the plain step, and it is now ~22% of a typical round.
- Each extra verify row costs 2.6 ms on the pair against 3.4 ms on one Studio. That is why wider verifies pay off more on the pair, and why the pair wants its own cost ladder.
- Accepted tokens per round are the same on both (0.5-0.6 extra at 2 rows, 1.3 at 3, 2.1 at 4).

## Reproduce
Builds used for these tables: stock v26.11.3 plus timers, and v26.11.3 + PR #1146 + the switches in this branch. A
locally patched libjaccl (MLX c69303b, the port's link-local GID; `JACCL_GID_LL=1`) was used only while one Mac had
lost its cable IPv4 address; it is not in this branch. Build with `zig build -Doptimize=ReleaseFast` and copy the same
build to both Macs. Benchmarks: `two-macs/scripts/bench_client.py`, `rw_bench.py` and `quality.py`.

By hand, the best DSpark pair is (cable addresses up):

```bash
# Mac 1 (rank 0). Keep this shell open.
env DSV41_TP_NAXMOE=1 DSV41_TP_FFNIN=3 DSV41_TP_SUMSPLIT=1 DSV41_SPARK_COST=0.89,1.04,0.147 DSV41_NO_BELL=1 \
  <build>/zig-out/bin/mlx-serve --serve \
  --host 127.0.0.1 --port 11240 --ctx-size 65536 --max-concurrent 1 --metrics --no-pld --no-plugins \
  --model-dir <MODELS> --dist tensor \
  --dist-model <MODELS>/DeepSeek-V4.1-Flash-1017-MLX-Serve-iQ-MLX-3.0bpw \
  --dist-coordinator <MAC1_CABLE_IP>:55100 --dist-device rdma_en13
# Mac 2 (rank 1), a few seconds later. Keep this shell open too.
env DSV41_TP_NAXMOE=1 DSV41_TP_FFNIN=3 DSV41_TP_SUMSPLIT=1 DSV41_SPARK_COST=0.89,1.04,0.147 DSV41_NO_BELL=1 \
  <build>/zig-out/bin/mlx-serve worker \
  --coordinator <MAC1_CABLE_IP>:55100 --device rdma_en4 --model-dir <MODELS>
```

Then send one request with model `DeepSeek-V4.1-Flash-1017-MLX-Serve-iQ-MLX-3.0bpw` (it loads both halves, ~30 s), and bench with `scripts/bench_client.py --model <that name>`. The cable addresses are lost at a reboot: set them again on both Macs (`sudo ifconfig <port> inet <address>/30 up`), one /30 per cable.

Raw data (every request with its generated text, and both ranks' logs per arm) is not included.

## Next
Each remaining idea is worth a few percent; none is a step change. In the order I would do them:
0. **Shorten the DSpark draft on the pair** (4.2 ms a round, not sped up by the split): fuse its small kernels, or cut its five sequential gathers to one. Up to ~5% on DSpark.
1. **Fix DSpark's plain-step estimate under `--dist`** so the policy learns the pair's costs itself instead of taking `DSV41_SPARK_COST`. Small change, upstreamable.
2. **Emit each rank's partial sum straight from the split kernels**, so the four-stream outputs are not sliced back to one (Astra's top pick, with caching launch configs; ~0.5-2 ms a step by its guess, of which FFNIN=3 already took ~0.45).
3. **Fewer, bigger kernels per layer.** ~420 kernel launches a step at ~24 us of host time each is most of the 10 ms.
4. Done 05:40-06:15: cable control channel and no bell (+4.8% on DSpark, nothing on plain).
5. **A second thread for Metal encoding**: up to ~2.7 ms of graph building could overlap, but the GPU is 93% busy on a half model, so the real gain is small, and Astra lists a page of MLX thread-safety hazards. Not worth it.
6. Worth upstreaming, with your OK (drafts are in `upstream-drafts/`, five files, nothing posted): the NAX MoE fix (65.5 -> 77.2 tok/s for every M5 pair on this pack), the uninitialised `tp_snaps` counter, FFNIN=3, link-local GIDs, and the DSpark estimate.

Second opinions on this plan: Neon's is `second-opinion/REVIEW2-neon.md` (it found the 40 evals a step, the 512 KiB striping threshold, that PR #1146 already splits the head, and that the draft does five tiny gathers in a row). Astra's is `second-opinion/REVIEW2-astra.md` (optimise host work per layer first; the encode thread is high risk; the 10-task limit and inline RDMA are near zero). Neither contradicts the order above; Astra would put item 2 first and did not look at item 1. Not tried from their lists: the direct partial outputs (item 2) and a 20/32/40/50 KiB sweep of in-graph sum sizes to explain the FFNIN=1 cliff.

---

# Background (written before the night runs)

## Setup
- 2x Mac Studio M5 Ultra 256 GB, macOS 27.2, TB5 RDMA (link at 21:01: one cable, Mac 1 `rdma_en13` <-> Mac 2 `rdma_en4`, Thunderbolt Bridge still on)
- mlx-serve 26.11.3 (Homebrew bottle) and a source build of tag v26.11.3 (MLX c69303b, built on the MacBook with Xcode 27.0)
- Pack: `ddalcu/DeepSeek-V4.1-Flash-1017-MLX-Serve-iQ-MLX-3.0bpw` rev 6da9c4e4 (40 layers, hidden 5120, 64 heads, 384 experts top-6, DSpark block 5)

## What the source says (v26.11.3)
- `--dist tensor` splits every routed/shared expert AND the attention heads (wq_b/wo_a rows, wo_b columns). Each layer does two all_sums (attention output, MoE output): **80 collectives per decode step** (`noteTpStep` treats 80 as the normal decode count).
- Each all_sum is a JACCL op on MLX's **CPU stream**: GPU -> fence -> CPU thread -> RDMA -> CPU -> fence -> GPU.
- `--dist`/`worker` already set `MLX_METAL_FAST_SYNCH=1` (shared-memory spin fences).
- DSpark/MTP already runs under tensor split (rank 0 drafts alone; verify rows ride the same 80 sums).
- With fast sync, MLX's `Fence::update` writes the GPU->CPU fence value inside the current command buffer but does not commit it. On Ultra chips MLX commits every 50 ops (`max_ops_per_buffer_ = 50`), so the CPU side of each all_sum can wait for that many more kernels to be encoded before the GPU even starts the buffer that signals it.

## Where the bytes are (pack tally, per decoded token)
Summed from the pack's safetensors headers (all 40 layers):

| per token, one Mac | GB |
|---|---|
| routed experts (203.8 GB total, 6 of 384 per token) | 3.18 |
| shared expert | 1.46 |
| attention (wq_a 0.27, wq_b 1.73, wkv 0.11, wo_a 2.68, wo_b 1.73, indexer/compressor 0.08) | 6.60 |
| hyper-connection fns | 0.16 |
| LM head (dense 1.39; mlx-serve requantizes to 8-bit, so ~0.7) | ~0.7 |
| **total** | **~12.1** |

- Attention is more than half of every token's reads in this pack (8-bit attention, ~3-bit experts). So **replicated attention** (whole heads on both Macs, one sum per layer instead of two) would raise each rank's reads from ~6.4 GB to ~9.6 GB and give up most of the split's gain. I dropped it for this pack.
- Stock split (heads + experts halved, head on rank 0): ~6.4 GB on rank 0 vs ~12.1 GB alone. At one Mac's measured ~14.3 ms/token (70 tok/s), halved reads are worth ~6.5 ms. That buys 80 collectives at ~80 µs each before break-even, and ~25 µs each for 1.5x.

## Measurements
### MacBook (M4 Pro), GPU<->CPU hand-off microbench (`bench/handoff.c`)
80 layers of (1x1024 @ 1024x1024 bf16 matmul + 10 small GPU ops), one graph, with and without a CPU-stream op per layer standing in for the all_sum:

| | GPU only | + CPU hop | cost per hop |
|---|---|---|---|
| `MLX_METAL_FAST_SYNCH=0` | 52.2 us/layer | 142.5 us/layer | ~90 us |
| `MLX_METAL_FAST_SYNCH=1` (what `--dist` sets) | 51.8 | 61.6 | **~10 us** |
| fast sync + my `MLX_FENCE_COMMIT=1` patch (commit right after the GPU->CPU fence) | | 61.0 best / 152 mean | no gain, more variance |

### The pair, `mlx-serve dist-probe` (stock build, no model), 2026-11-19 ~21:50
Cables: 1 = Mac 1 `rdma_en13` <-> Mac 2 `rdma_en4`; 2 = Mac 1 `rdma_en4` <-> Mac 2 `rdma_en3`, each on its own /30. Thunderbolt Bridge off. Apple's `ibv_uc_pingpong` fails on both cables, but JACCL connects fine.

| | cable 1 | cable 2 |
|---|---|---|
| round trip 4 B (mean / best) | 39.6 / 27.5 us | 55.3 / 41.7 us |
| round trip 20 KB | 44.3 / 36.8 us | 51.2 / 43.7 us |
| round trip 25 MB | 9.27 GB/s each way | 9.28 GB/s |
| all_sum bf16 20 KB (CPU-side, back to back) | **21.7 us** | **20.0 us** |
| all_sum bf16 512 KB | 110 us | 105 us |

`--chain` (40 layers, each a 1x5120 @ 5120x5120 bf16 matmul on the GPU, then an all_sum, then a GPU op), per layer:

| mode | probe default (no fast sync) | `MLX_METAL_FAST_SYNCH=1` (what serving uses) |
|---|---|---|
| no_all_sum (GPU only) | 424.8 us | 424.7 us |
| one_graph (GPU + all_sum per layer) | 664.6 us | **452.0 us** |
| all_sum_only (GPU op <-> all_sum, no matmul) | 215.2 us | **22.6 us** |
| cpu_only (all_sum between CPU ops) | 10.6 us | 9.3 us |

- **One collective inside a GPU graph costs ~27 us with fast sync** (452.0 - 424.7). Without it, ~240 us. Note that `dist-probe` doesn't set fast sync itself (only `serve`/`worker` do), so its default `--chain` numbers (and the "650 us a layer" quoted in PR #1146) are the slow-fence path, not what serving sees.
- 80 collectives x ~27 us = ~2.2 ms per decode step: under the ~6.5 ms break-even budget, and close to the 1.5x target.
- (The 1x5120 @ 5120x5120 matmul taking 425 us is MLX's transposed bf16 GEMV, not a bandwidth number.)

So MLX's fast fence is cheap, and committing early doesn't help: the extra command buffers trip MLX's active-task throttle. On the Studios each collective's cost should come mostly from JACCL's RDMA round trip, not from the GPU/CPU hand-off.

## Outside research (run separately, 2026-11-19; I spot-checked the MLX/mlx-serve citations)
- Apple's Thunderbolt RDMA is two-sided UC SEND/RECV only (TN3205): no RDMA_WRITE, no way for a Metal shader to see or send RDMA data without the CPU. Nothing to gain below JACCL.
- MLX after v0.32.4: no GPU-side all_sum and no fence changes (mlx #4438: default fence ~180 us per crossing, fast sync ~4 us; this matches my 240 us vs 27 us). JACCL only stripes across both cables from 512 KiB (`MESH_MULTI_WIRE_MIN_BYTES`), so the second cable can't help 20 KB sums; 32 KiB is where its buffer class changes.
- The #1237 hang looks like MLX's known fast-sync `fence_wait` wedge (mlx #3142, closed as won't-fix): the GPU stays stuck until reboot. No fix posted on #1237.
- mlx #3207: ~60 JACCL init/teardown cycles exhaust RDMA protection domains until reboot, so pair launches are rationed.
- Published result for this model: one M5 Ultra 1.5-2x faster than two (Reddit, mlx-serve 26.11.2, Lossless pack). Apple's 1.7x pair speedups are on models with 50-130 ms steps; this one is 14 ms.
- PR #1146 is still open and unmerged (head add11dd9, the commit I built).
