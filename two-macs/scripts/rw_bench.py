#!/usr/bin/env python3
"""Real-world bench against an OpenAI-compatible mlx-serve: prompt length, follow-up turns, concurrent streams.

Three suites, one JSON line per request appended to --out (field "suite"):
  len    one stream, a cold prompt of ~N tokens (N from --lens), then a follow-up turn on the same conversation
         (so the prefix is cached): TTFT, prompt tok/s, decode tok/s for both.
  conc   C streams started together (C from --conc), each a different ~100-token prompt: per-stream TTFT and
         decode tok/s, and the aggregate tok/s over the wall time.
  ttft   short interactive turns (--effort-ttft, default "low"): TTFT to the first reasoning chunk and to the
         first answer (content) chunk.
Long prompts are built from varied numbered records, never a short repeated string (mlx-serve #1237).
"""
import argparse, json, random, threading, time, urllib.request

MODEL = "default"
BASE = [
    "Explain, for a graduate systems course, how a modern out-of-order CPU core hides memory latency. Cover the reorder buffer, load/store queues, memory disambiguation and hardware prefetchers, with one worked example.",
    "Write a careful comparison of Raft, multi-Paxos and leaderless quorum replication. Discuss failure modes, read/write latency and what each costs an operator, and say when you would pick each.",
    "A small bakery wants to decide whether to buy a second oven. Daily demand is roughly normal with mean 420 loaves and standard deviation 90; one oven bakes 300 loaves a day. Work through the decision with explicit numbers.",
    "Describe the life cycle of a massive star from the main sequence to a core-collapse supernova, including the burning stages, the role of neutrinos and what is left behind.",
    "Design a Python library API for scheduling background jobs with retries, exponential backoff, per-queue rate limits and idempotency keys. Show the public classes with docstrings and one usage example.",
    "Summarize the main causes and consequences of the 1970s stagflation in the United States, contrasting monetarist and Keynesian explanations and the role of oil shocks.",
    "Explain how TLS 1.3 establishes a session, what changed from TLS 1.2, and where 0-RTT resumption is unsafe. Give a concrete replay scenario.",
    "Plan a two-week itinerary through northern Japan by rail in winter for two adults who like food and hot springs, with daily travel times and one fallback per day for bad weather.",
]
ADJ = "northern coastal inland upland riverside eastern central remote older newer smaller larger".split()
NOUN = "depot clinic foundry orchard substation quarry archive hatchery refinery observatory cannery workshop".split()
CITY = "Aldermoor Brightwater Calder Dunmere Eastfold Farrow Glenhaven Harwick Iverness Juniper Kessock Larkhill Marrow Northam Oakhurst Penrose".split()
THING = "copper wire, barley, lamp oil, glass panes, salted fish, machine parts, wool bales, river clay, timber, printed forms, seed potatoes, tin plate".split(", ")
MONTH = "January February March April May June July August September October November December".split()
NOTE = [
    "which the inspector attributed to a late thaw", "although two shipments were turned back at the bridge",
    "after the night shift was doubled", "despite a shortage of trained hands", "once the new ledger system was adopted",
    "following a dispute over the weighing scales", "while the main road was closed for repairs",
    "because the spring floods arrived early", "as the district auditor had predicted", "before the tariff changed",
]


def records(n_tokens, seed):
    """About n_tokens of numbered, varied records (roughly 30 tokens each)."""
    rnd = random.Random(seed)
    out = []
    for i in range(max(1, n_tokens // 30)):
        out.append(
            f"Record {1000 + i}: the {rnd.choice(ADJ)} {rnd.choice(NOUN)} at {rnd.choice(CITY)} logged "
            f"{rnd.randint(12, 9800)} units of {rnd.choice(THING)} in {rnd.choice(MONTH)} {rnd.randint(1871, 1913)}, "
            f"{rnd.choice(NOTE)}."
        )
    return "\n".join(out)


def stream(url, messages, max_tokens, effort, temp=0.0):
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "stream": True,
            "stream_options": {"include_usage": True}, "temperature": temp, "reasoning_effort": effort}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    first = first_content = last = None
    n = 0
    usage = timings = None
    reasoning, content = [], []
    err = None
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
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
                usage = j.get("usage") or usage
                timings = j.get("timings") or timings
                for ch in j.get("choices") or []:
                    d = ch.get("delta") or {}
                    r_txt = d.get("reasoning_content") or d.get("reasoning") or ""
                    c_txt = d.get("content") or ""
                    if r_txt or c_txt:
                        now = time.time()
                        first = first or now
                        if c_txt and first_content is None:
                            first_content = now
                        last = now
                        n += 1
                        reasoning.append(r_txt)
                        content.append(c_txt)
    except Exception as e:  # a refused or failed stream is a result too
        err = repr(e)[:200]
    t_end = time.time()
    ctoks = (usage or {}).get("completion_tokens")
    dec = None
    if first and last and last > first:
        dec = ((ctoks or n) - 1) / (last - first)
    return {
        "t0": t0, "t_end": t_end, "err": err,
        "ttft_s": round(first - t0, 3) if first else None,
        "ttfa_s": round(first_content - t0, 3) if first_content else None,
        "wall_s": round(t_end - t0, 3),
        "completion_tokens": ctoks, "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "cached_tokens": ((usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens"),
        "decode_tok_s_client": round(dec, 2) if dec else None,
        "timings": timings,
        "reasoning": "".join(reasoning), "content": "".join(content),
    }


def emit(a, rec):
    rec.update({"label": a.label, "t": time.strftime("%H:%M:%S")})
    slim = {k: v for k, v in rec.items() if k not in ("reasoning", "content", "t0", "t_end")}
    print(json.dumps(slim), flush=True)
    with open(a.out, "a") as f:
        f.write(json.dumps({k: v for k, v in rec.items() if k not in ("t0", "t_end")}) + "\n")


def suite_len(a):
    for n in [int(x) for x in a.lens.split(",")]:
        if n <= 150:
            first_msg = f"[{a.nonce} len{n}] " + BASE[0]
        else:
            first_msg = (f"[{a.nonce} len{n}] Below are archive records from a regional trade survey.\n\n"
                         + records(n, seed=n) +
                         "\n\nUsing only the records above, describe three patterns you see across places and years, "
                         "and cite the record numbers that support each one.")
        msgs = [{"role": "user", "content": first_msg}]
        r = stream(a.url, msgs, a.max_tokens, a.effort)
        emit(a, dict(r, suite="len", target=n, turn=1))
        if r["err"]:
            continue
        # Follow-up on the same conversation: the prefix should come from the cache.
        msgs += [{"role": "assistant", "content": r["content"] or "(no answer yet)"},
                 {"role": "user", "content": "Now pick the single most surprising record and explain in a paragraph why it stands out."}]
        r2 = stream(a.url, msgs, a.max_tokens, a.effort)
        emit(a, dict(r2, suite="len", target=n, turn=2))


def suite_conc(a):
    for c in [int(x) for x in a.conc.split(",")]:
        res = [None] * c

        def run(k):
            res[k] = stream(a.url, [{"role": "user", "content": f"[{a.nonce} c{c} s{k}] " + BASE[k % len(BASE)]}],
                            a.max_tokens, a.effort)

        th = [threading.Thread(target=run, args=(k,)) for k in range(c)]
        t0 = time.time()
        for t in th:
            t.start()
        for t in th:
            t.join()
        wall = time.time() - t0
        toks = sum((r["completion_tokens"] or 0) for r in res)
        for k, r in enumerate(res):
            emit(a, dict(r, suite="conc", streams=c, stream=k, agg_tok_s=round(toks / wall, 2), agg_wall_s=round(wall, 2)))


def suite_ttft(a):
    qs = ["What is the capital of Australia, and why is it not Sydney?",
          "Give me a one-paragraph explanation of what a mutex is.",
          "Convert 72 degrees Fahrenheit to Celsius and show the arithmetic.",
          "Suggest three names for a hardware store's loyalty program."]
    for i, q in enumerate(qs):
        r = stream(a.url, [{"role": "user", "content": f"[{a.nonce} q{i}] " + q}], 300, a.effort_ttft)
        emit(a, dict(r, suite="ttft", q=i, effort=a.effort_ttft))


def suite_sys(a):
    """A long shared system prompt (agent instructions, tool list) with a different user question each time: every
    request after the first should reuse the system prompt's prefix."""
    for n in [int(x) for x in a.lens.split(",")]:
        system = (f"[{a.nonce} sys{n}] You are the archivist for a regional trade survey. Answer only from these records.\n\n"
                  + records(n, seed=7000 + n))
        qs = ["Which place appears most often, and in which years?",
              "List three records that mention a shortage or a dispute, with their numbers.",
              "What goods were logged in the largest quantities? Give the record numbers."]
        for i, q in enumerate(qs):
            r = stream(a.url, [{"role": "system", "content": system}, {"role": "user", "content": q}], a.max_tokens, a.effort)
            emit(a, dict(r, suite="sys", target=n, q=i))


def suite_switch(a):
    """Two conversations taking turns (A1, B1, A2, B2, A3, B3): each later turn should find its own conversation cached."""
    for n in [int(x) for x in a.lens.split(",")]:
        convs = []
        for c in range(2):
            convs.append([{"role": "user", "content": f"[{a.nonce} sw{n} conv{c}] Below are archive records from a regional trade survey.\n\n"
                           + records(n, seed=9000 + n + c) + "\n\nDescribe two patterns you see, citing record numbers."}])
        follow = ["Which single record is the most surprising, and why?", "Now summarise everything so far in three sentences."]
        for turn in range(3):
            for c in range(2):
                r = stream(a.url, convs[c], a.max_tokens, a.effort)
                emit(a, dict(r, suite="switch", target=n, conv=c, turn=turn + 1))
                if turn < 2:
                    convs[c] += [{"role": "assistant", "content": r["content"] or "(no answer yet)"},
                                 {"role": "user", "content": follow[turn]}]


def suite_many(a):
    """--conc-many conversations opened one after another (each ~N tokens), then each gets a follow-up in the same order:
    how many still find their conversation in the cache."""
    for n in [int(x) for x in a.lens.split(",")]:
        convs = []
        for c in range(a.many):
            m = [{"role": "user", "content": f"[{a.nonce} many{n} conv{c}] Below are archive records from a regional trade survey.\n\n"
                  + records(n, seed=20000 + 31 * c + n) + "\n\nDescribe two patterns you see, citing record numbers."}]
            r = stream(a.url, m, 48, a.effort)
            emit(a, dict(r, suite="many", target=n, conv=c, turn=1))
            convs.append(m + [{"role": "assistant", "content": r["content"] or "(no answer yet)"},
                              {"role": "user", "content": "Which single record is the most surprising, and why?"}])
        for c, m in enumerate(convs):
            r = stream(a.url, m, 48, a.effort)
            emit(a, dict(r, suite="many", target=n, conv=c, turn=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="default")
    ap.add_argument("--url", default="http://127.0.0.1:11240")
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", default="rw.jsonl")
    ap.add_argument("--suites", default="ttft,len,conc")
    ap.add_argument("--lens", default="100,2000,8000,24000")
    ap.add_argument("--conc", default="1,2,3,4,6,8,12,16")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--effort", default="max")
    ap.add_argument("--effort-ttft", default="low")
    ap.add_argument("--nonce", default="a")
    ap.add_argument("--many", type=int, default=24)
    a = ap.parse_args()
    global MODEL
    MODEL = a.model
    for s in a.suites.split(","):
        {"len": suite_len, "conc": suite_conc, "ttft": suite_ttft, "sys": suite_sys, "switch": suite_switch, "many": suite_many}[s](a)


if __name__ == "__main__":
    main()
