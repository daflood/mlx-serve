# 4-bit DeepSeek-V4.1-Flash on two 256 GB Mac Studios

This branch is mlx-serve v26.11.3 + open PR #1146 + experimental switches for a pair of M5 Ultra Macs. It is not an official mlx-serve release. The numbers below come from `two-macs/bigpack-REPORT.md` ("Confirmed on the public pack") and `two-macs/REPORT.md`.

The 4-bit pack, [`mlx-community/DeepSeek-V4.1-Flash-1017-oQ4e-ngram-mtp`](https://huggingface.co/mlx-community/DeepSeek-V4.1-Flash-1017-oQ4e-ngram-mtp), keeps every weight at the precision DeepSeek released (4-bit experts, 8-bit trunk, 8-bit Engram tables). It needs 288 GiB of memory, more than one 256 GB Mac's GPU limit (232 GiB). This branch of mlx-serve runs it across two M5 Ultra Studios joined by one Thunderbolt 5 RDMA cable:

| | one Studio, 3-bit pack (the biggest that fits) | two Studios, 4-bit, stock 26.11.3 | **two Studios, 4-bit, this branch** |
|---|---|---|---|
| 1 user, tok/s | 79.0 | 74.0-74.5 | **92.8-93.6** |
| 2 users, total | 94.2 | 99.2-99.5 | **116.4** |
| 4 users, total | 124.0 | 135.0-135.9 | **150.8-151.1** |
| 8 users, total | not measured | 171.2-172.1 | **178.5-179.6** |
| decode bench (DSpark, 9 prompts) | 79.7 | 78.0 (68-90) | **103.5** (96-115) |
| first token, new 26,800-token prompt | 6.89 s | 7.43 s | 7.40 s |
| first token, new question behind a 26,800-token shared prompt | | 7.4-7.5 s | **0.25-0.26 s** |
| first token, follow-up on a cached prompt | 0.12-0.15 s | 0.10-0.11 s | 0.09-0.11 s |

Real prompts, 768-token answers, reasoning effort max, temperature 0, DSpark on, prompt-lookup decoding off (`--no-pld`), two passes each. The patches add +25% for one user, +17% / +11% / +4% at 2 / 4 / 8.

Long context (same weights, earlier folder layout): 8 users at 111k tokens each fit with about 55 GiB to spare per Studio. A new 111k prompt takes 33 s; new prompts are read one at a time; follow-ups on a cached one start in 0.15 s.

Tested only on M5 Ultra 256 GB with this pack.

## What the branch changes

Every change sits behind an environment switch and is off by default. **Both Macs must set the same switches.**

| switch | what it does |
|---|---|
| `DSV41_FP4_NAX=1` | **the main fix for this pack.** On M5 the fused MoE kernels only take 2-3 bit experts, so 4-bit (mxfp4) experts ran on a slow fallback. This builds the fused mxfp4 kernel for M5 and uses it under the split. Switching it on took the decode bench from 83.1 to 101.4 tok/s (on the earlier `oQ4e-mtp` pack, all other switches the same). |
| `DSV41_TP_SHARE=1` | needed because of `DSV41_NO_BELL=1`: without the bell the worker never reports its free memory, so rank 0 bills itself the whole pack and refuses a pack bigger than one Mac. This bills each Mac its share. Not needed if you leave `DSV41_NO_BELL` unset. |
| `DSV41_TP_FFNIN=3` | fused FFN entry on the mxfp4 kernel, plus a Metal kernel for the mixing around each cross-Mac sum. Plain decode +6%. |
| `DSV41_TP_SUM=bf16` | half the bytes per cross-Mac sum at 7-16 rows. +2-3% at 4-8 users. |
| `DSV41_TP_SLICE=1` | shared-prefix prompt caching under the split (same system prompt, new question). 7.4 s to 0.25 s at 26,800 tokens. |
| `DSV41_TP_SUMSPLIT=1`, `DSV41_SPARK_COST=0.89,1.04,0.147`, `DSV41_NO_BELL=1`, `DSV41_TP_NAXMOE=1` | smaller fixes from the 3-bit work (keeps each sum under 32 KB, DSpark draft costs for a pair, RDMA wait instead of a TCP wake-up, fused kernels for 2-3 bit packs). Harmless on this pack. |

A multi-user switch from our earlier notes, `DSV41_TP_BATCHFUSED`, corrupted output with several users at once and is removed from this branch. `DSV41_TP_SPAN_SUM`, `DSV41_TP_WIDE_SORT` and `DSV41_FP4_PAIRED` measured slower or no gain; leave them unset. `DSV41_TP_FAKESUM` is a timing diagnostic that produces garbage.

## Before you start

- Two M5 Ultra Macs, 256 GB each, Thunderbolt 5, RDMA enabled (macOS 26.2 or later; enable RDMA once per Mac in Recovery). Tested on macOS 27.2.
- One Thunderbolt 5 cable between them. A second cable made no difference in our tests.
- **If you connect two cables, take the cable ports out of Thunderbolt Bridge.** macOS adds every Thunderbolt port to `bridge0`, so two cables between the same Macs form a loop: about 200,000 packets a second per port, `mDNSResponder` and `netbiosd` each eating a core. RDMA keeps working, so it's easy to miss. Check with `ps -Ao pcpu,command -r | head -4`. Fix: `sudo ifconfig bridge0 deletem <enX>` per cable port, made permanent with a launch daemon.
- Give each cable port an IPv4 address on its own small subnet (a /30), also from a launch daemon, because `ifconfig` addresses are lost at reboot. `ibv_devinfo | grep -B1 ACTIVE` shows the RDMA device names (`rdma_enX`).
- Nothing else holding memory on either Mac (other model servers, login agents). The pack leaves about 75 GiB of the GPU limit free on each.
- About 480 GB free disk on each Mac.

## Get the model onto both Macs

Each Mac needs the whole pack at the same path (477 GiB). Download it once:

```bash
hf download mlx-community/DeepSeek-V4.1-Flash-1017-oQ4e-ngram-mtp
```

One connection to Hugging Face's CDN is slow and uneven. A multi-connection downloader (aria2c, 16 connections per file) filled a 2 Gb/s line for us; `two-macs/scripts/hfget` in this branch does that and checks every file's SHA-256.

Then copy it to the second Mac over the Thunderbolt cable, not over the internet a second time and not through `rsync`/`scp` over ssh (about 0.5 GB/s, one CPU core of encryption). A plain TCP copy over the cable did 3.7 GB/s for us.

## Build

The same binary must run on both Macs. Check `shasum -a 256 zig-out/bin/mlx-serve` on both before every launch.

```bash
git clone --recurse-submodules -b dsv41-two-macs https://github.com/daflood/mlx-serve && cd mlx-serve
```

Build the server as in upstream's `docs/building.md` (release build), and copy the build to the second Mac.

## Run

Start rank 0 first, with `--model-dir` and **not** `--model` (with `--model` it exits before the worker can join). Keep that shell open.

```bash
export DSV41_FP4_NAX=1 DSV41_TP_SHARE=1 DSV41_TP_FFNIN=3 DSV41_TP_SUM=bf16 DSV41_TP_SLICE=1 \
       DSV41_TP_SUMSPLIT=1 DSV41_SPARK_COST=0.89,1.04,0.147 DSV41_NO_BELL=1 DSV41_TP_NAXMOE=1
M=<MODELS>/DeepSeek-V4.1-Flash-1017-oQ4e-ngram-mtp

# Mac 1 (rank 0)
./zig-out/bin/mlx-serve --serve --host 127.0.0.1 --port 11240 \
  --ctx-size 65536 --max-concurrent 16 --no-pld \
  --model-dir <MODELS> --dist tensor --dist-model $M \
  --dist-coordinator <MAC1_CABLE_IP>:55100 --dist-device <rdma_enX>

# Mac 2 (worker), a few seconds later, same exports
./zig-out/bin/mlx-serve worker --coordinator <MAC1_CABLE_IP>:55100 \
  --device <rdma_enY> --model-dir <MODELS>
```

Send one chat request with the model name `DeepSeek-V4.1-Flash-1017-oQ4e-ngram-mtp`. That loads both halves (about 30 s). The API is OpenAI-compatible at `http://127.0.0.1:11240/v1` on Mac 1.

- `--no-pld` matches how we measured. Prompt-lookup decoding (on by default) copies tokens from the prompt and can be much faster when the answer repeats it, as in code edits. Try both on your own work.
- For long contexts raise `--ctx-size` (we ran 262,144) and the prompt cache (`--prefix-cache-entries`, `--prefix-cache-mem`).
- Optional warm-up: the first long prompt after a launch is slow. Three prompts of about 700, 2,600 and 9,100 tokens at start (about 6 s) remove that.

## Things that will bite you

- **The worker never joins, or gets "accepted then closed".** The macOS firewall on Mac 1 (especially in stealth mode) is likely dropping the dial for a new binary path. Allow the binary, or put the coordinator on `127.0.0.1` and reach it from Mac 2 through `ssh -L 55100:127.0.0.1:55100 <mac1>`. The tunnel only carries the join; RDMA data still uses the cable.
- **Started over ssh?** Keep that ssh session open if the process dials a non-loopback address. macOS blocks local-network connections from a process whose ssh session ended, and it shows up as a timeout (error 60).
- **`Couldn't allocate protection domain`.** Each RDMA init/teardown leaks a protection domain (mlx issue #3207). After about 60 launches, reboot. Batch your tests.
- **With `DSV41_NO_BELL=1`, rank 0 does not check that the worker has the same model.** Put the same pack folder at the same path on both Macs.
- **Don't probe the coordinator port with `nc`.** Rank 0 accepts exactly one connection, and the probe takes it.
- **Stopping:** stop Mac 1's server first, then the worker. Let requests finish; don't kill a pair mid-forward (a stuck GPU after a kill needs a reboot, upstream issue #1237).

## Check your answers, not just your speed

A multi-user switch that looked fine on speed corrupted output; a 48-question check with checkable answers caught it. Before trusting any new switch, run `two-macs/scripts/quality.py` three ways (one at a time, `--par 4`, `--sys 9000`). It should score 48/48 with no `begin▁of▁sentence` tokens in the output. These settings do, all three ways.

## Limits

- Two users who each want full speed get about 58-60 tok/s each on the pair. Two separate Studios on the 3-bit pack give each about 77-80. The pair's case is running the 4-bit pack at all.
- A new long prompt is a little slower than the 3-bit pack on one Studio (7.4 s against 6.9 s at 26,800 tokens).
- `zig build test` on an M5: one test, "ffn prefill, GGUF experts ... within twice the per-pair gathers' distance", fails. It fails the same way on the PR #1146 merge without this branch's changes, and passes on upstream main. The DSpark "legacy shell" test fails now and then, also on main-based branches.
- One setup, one pack. Please post your numbers, especially other Macs and other packs.

## Files

- `two-macs/patches/pr1146-to-two-macs.diff`: the changes as one diff against v26.11.3 + PR #1146
- `two-macs/scripts/rw_bench.py`, `two-macs/scripts/bench_client.py`: the benchmarks behind the numbers
- `two-macs/scripts/quality.py`: the 48-question answer check
- `two-macs/scripts/hfget`: multi-connection Hugging Face download with SHA-256 checks
- `two-macs/REPORT.md`, `two-macs/bigpack-REPORT.md`: the full lab notes, including what didn't help
