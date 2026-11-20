#!/usr/bin/env python3
"""Single-user decode bench against an OpenAI-compatible mlx-serve.

Streams chat requests (thinking on, reasoning_effort=max), records TTFT, wall decode tok/s
(chunks after the first / time after the first), reasoning vs content chars, and the server's
own usage/timings if it sends them. Prompts are long and varied (avoid #1237's short repetitive
prompt shape). Appends one JSON line per request to --out.
"""
import argparse, json, time, urllib.request, sys

PROMPTS = [
    "Explain, for a graduate systems course, how a modern out-of-order CPU core hides memory latency. Cover the reorder buffer, load/store queues, memory disambiguation, hardware prefetchers, and how these interact with branch misprediction recovery. Give one concrete worked example with cycle counts.",
    "Write a careful comparison of three approaches to consensus in distributed databases: Raft, multi-Paxos, and leaderless quorum replication as in Dynamo. Discuss failure modes, read/write latency in a geo-distributed deployment across three continents, and operational complexity. End with a recommendation for a payments ledger.",
    "A small bakery wants to decide whether to buy a second oven. Daily demand is uncertain, roughly normal with mean 420 loaves and standard deviation 90; one oven bakes 300 loaves a day. Work through the expected profit with and without the second oven, stating every assumption about prices, costs and depreciation, and discuss risk.",
    "Describe the life cycle of a massive star from the main sequence to a core-collapse supernova, including the nuclear burning stages, the role of neutrinos, the formation of a neutron star or black hole, and which elements are produced where. Mention at least two open research questions.",
    "Design a Python library API for scheduling background jobs with retries, exponential backoff, rate limits per queue, and idempotency keys. Show the public classes and methods with docstrings, one example of usage, and explain how you would test it without real sleeps.",
    "Summarize the main causes and consequences of the 1970s stagflation in the United States, contrasting monetarist and Keynesian explanations, the role of oil shocks, wage-price dynamics, and the Volcker disinflation. Keep it balanced and cite the kinds of data each side relies on.",
]

MODEL = "default"

def one(url, prompt, max_tokens, effort, temp):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": temp,
        "reasoning_effort": effort,
    }
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    first = None
    n_chunks = 0
    rc = cc = 0
    text = []
    usage = None
    timings = None
    last = None
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
            except json.JSONDecodeError:
                continue
            if j.get("usage"):
                usage = j["usage"]
            if j.get("timings"):
                timings = j["timings"]
            for ch in j.get("choices") or []:
                d = ch.get("delta") or {}
                r_txt = d.get("reasoning_content") or d.get("reasoning") or ""
                c_txt = d.get("content") or ""
                if r_txt or c_txt:
                    now = time.time()
                    if first is None:
                        first = now
                    last = now
                    n_chunks += 1
                    text.append(r_txt + c_txt)
                    rc += len(r_txt)
                    cc += len(c_txt)
    t_end = time.time()
    ctoks = (usage or {}).get("completion_tokens")
    dec = None
    if first and last and last > first:
        toks_after_first = (ctoks - 1) if ctoks else (n_chunks - 1)
        dec = toks_after_first / (last - first)
    return {
        "ttft_s": round(first - t0, 3) if first else None,
        "wall_s": round(t_end - t0, 3),
        "completion_tokens": ctoks,
        "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "chunks": n_chunks,
        "decode_tok_s_client": round(dec, 2) if dec else None,
        "reasoning_chars": rc,
        "content_chars": cc,
        "timings": timings,
        "text": "".join(text),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="default")
    ap.add_argument("--url", default="http://127.0.0.1:11240")
    ap.add_argument("--label", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--effort", default="max")
    ap.add_argument("--temp", type=float, default=0.0)
    ap.add_argument("--prompts", default="0,1,2")
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--nonce", default="a", help="same across arms so they generate the same text; change it to re-run inside one server launch")
    a = ap.parse_args()
    global MODEL
    MODEL = a.model
    idx = [int(x) for x in a.prompts.split(",")]
    for rep in range(a.reps):
        for i in idx:
            # The tag is the same for every arm (same text at temp 0), and differs per rep so the prefix cache misses.
            tag = f"[run {a.nonce} r{rep} p{i}] "
            res = one(a.url, tag + PROMPTS[i], a.max_tokens, a.effort, a.temp)
            res.update({"label": a.label, "rep": rep, "prompt": i, "max_tokens": a.max_tokens,
                        "effort": a.effort, "t": time.strftime("%H:%M:%S")})
            print(json.dumps({k: v for k, v in res.items() if k != "text"}), flush=True)
            with open(a.out, "a") as f:
                f.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
