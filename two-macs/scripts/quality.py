#!/usr/bin/env python3
"""quality.py: 48 questions with one checkable answer each, temperature 0, to compare the pair's answers with one Studio's.
Appends one JSON line per question to --out; prints the score. Same CLI shape as rw_bench.py (--label --out --model --url)."""
import argparse, json, re, time, urllib.request

Q = [
 ("What is 17 * 23? Reply with the number only.", r"\b391\b"),
 ("What is 1001 - 387? Reply with the number only.", r"\b614\b"),
 ("What is 2 to the power of 13? Reply with the number only.", r"\b8,?192\b"),
 ("What is 144 divided by 16? Reply with the number only.", r"\b9\b"),
 ("What is the remainder when 1000 is divided by 7? Reply with the number only.", r"\b6\b"),
 ("What is 15% of 240? Reply with the number only.", r"\b36\b"),
 ("What is the sum of the integers from 1 to 50? Reply with the number only.", r"\b1,?275\b"),
 ("What is the greatest common divisor of 84 and 126? Reply with the number only.", r"\b42\b"),
 ("How many prime numbers are there below 30? Reply with the number only.", r"\b10\b"),
 ("What is the square root of 1764? Reply with the number only.", r"\b42\b"),
 ("A train travels 180 km in 2.5 hours. What is its average speed in km/h? Reply with the number only.", r"\b72\b"),
 ("If 3x + 7 = 31, what is x? Reply with the number only.", r"\b8\b"),
 ("What is 7 factorial? Reply with the number only.", r"\b5,?040\b"),
 ("Convert 100 degrees Celsius to Fahrenheit. Reply with the number only.", r"\b212\b"),
 ("How many seconds are in a day? Reply with the number only.", r"\b86,?400\b"),
 ("What is the next number in the sequence 2, 6, 12, 20, 30? Reply with the number only.", r"\b42\b"),
 ("What is the capital of Australia? Reply with one word.", r"Canberra"),
 ("What is the chemical symbol for gold? Reply with the symbol only.", r"\bAu\b"),
 ("Which planet is the largest in the Solar System? Reply with one word.", r"Jupiter"),
 ("In which year did the Second World War end? Reply with the year only.", r"\b1945\b"),
 ("Who wrote the play Hamlet? Reply with the surname only.", r"Shakespeare"),
 ("What is the atomic number of carbon? Reply with the number only.", r"\b6\b"),
 ("How many sides does a hexagon have? Reply with the number only.", r"\b6\b"),
 ("What is the longest river in Africa? Reply with one word.", r"Nile"),
 ("What gas do plants absorb from the air for photosynthesis? Reply with its chemical formula.", r"CO\s?2|CO₂"),
 ("What is the capital of Canada? Reply with one word.", r"Ottawa"),
 ("How many continents are there? Reply with the number only.", r"\b7\b|seven"),
 ("What is the freezing point of water in Kelvin, to the nearest whole number? Reply with the number only.", r"\b273\b"),
 ("Which element has the chemical symbol Fe? Reply with one word.", r"[Ii]ron"),
 ("What is the smallest prime number greater than 100? Reply with the number only.", r"\b101\b"),
 ("Spell the word 'strawberry' backwards. Reply with the reversed word only.", r"yrrebwarts"),
 ("How many times does the letter 'r' appear in the word 'strawberry'? Reply with the number only.", r"\b3\b|three"),
 ("Sort these numbers from smallest to largest: 42, 7, 19, 3, 88. Reply with the numbers separated by commas.", r"3,\s*7,\s*19,\s*42,\s*88"),
 ("Alice is taller than Bob. Bob is taller than Carol. Who is the shortest? Reply with the name only.", r"Carol"),
 ("If today is Wednesday, what day of the week will it be 10 days from now? Reply with the day only.", r"Saturday"),
 ("A bat and a ball cost 1.10 in total. The bat costs 1.00 more than the ball. How much does the ball cost, in cents? Reply with the number only.", r"\b5\b"),
 ("What is the binary representation of the decimal number 45? Reply with the binary digits only.", r"\b101101\b"),
 ("What is the hexadecimal representation of the decimal number 255? Reply with the hex digits only.", r"\b(0x)?[Ff][Ff]\b"),
 ("In Python, what does len('hello world') return? Reply with the number only.", r"\b11\b"),
 ("In Python, what is the value of 7 // 2? Reply with the number only.", r"\b3\b"),
 ("In Python, what does sorted([3, 1, 2])[0] return? Reply with the number only.", r"\b1\b"),
 ("What HTTP status code means 'Not Found'? Reply with the number only.", r"\b404\b"),
 ("How many bits are in a byte? Reply with the number only.", r"\b8\b|eight"),
 ("What is the time complexity of binary search on a sorted array of n items, in big-O notation? Reply with the notation only.", r"O\(\s*log\s*_?2?\s*\(?n\)?\s*\)"),
 ("A rectangle is 12 cm long and 5 cm wide. What is the length of its diagonal in cm? Reply with the number only.", r"\b13\b"),
 ("What is the area of a circle with radius 3, as a multiple of pi? Reply in the form 'N pi'.", r"\b9\s*(pi|π|\\pi)"),
 ("Three people share 5 pizzas equally; each pizza has 6 slices. How many slices does each person get? Reply with the number only.", r"\b10\b"),
 ("What is 0.125 as a fraction in lowest terms? Reply with the fraction only.", r"\b1\s*/\s*8\b"),
]

def ask(url, model, q, effort, system=None):
    body = {"model": model, "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": q}], "max_tokens": 700, "temperature": 0.0, "reasoning_effort": effort}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.loads(r.read())
    m = j["choices"][0]["message"]
    return (m.get("content") or ""), (m.get("reasoning_content") or m.get("reasoning") or ""), j["choices"][0].get("finish_reason")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="default"); ap.add_argument("--url", default="http://127.0.0.1:11240")
    ap.add_argument("--label", required=True); ap.add_argument("--out", default="quality.jsonl"); ap.add_argument("--effort", default="low")
    ap.add_argument("--par", type=int, default=1); ap.add_argument("--sys", type=int, default=0); ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    # --par N: N questions at a time (the batched decode path). --sys N: every question behind one shared system prompt of
    # about N tokens (the shared-prefix cache path); the records are filler, the instruction is to answer the question.
    system = None
    if a.sys:
        import rw_bench
        system = "You are a careful assistant. The archive records below are background only; answer the user's question exactly as asked.\n\n" + rw_bench.records(a.sys, a.seed)
    import concurrent.futures
    def one(i):
        q, pat = Q[i]
        try:
            content, reasoning, fin = ask(a.url, a.model, q, a.effort, system)
        except Exception as e:
            content, reasoning, fin = "", "", repr(e)[:100]
        return i, bool(re.search(pat, content)), content, reasoning, fin
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(a.par) as ex:
        for i, good, content, reasoning, fin in ex.map(one, range(len(Q))):
            ok += good
            with open(a.out, "a") as f:
                f.write(json.dumps({"label": a.label, "i": i, "ok": good, "finish": fin, "content": content, "reasoning": reasoning, "t": time.strftime("%H:%M:%S")}) + "\n")
            print(f"q{i:02d} {'ok ' if good else 'MISS'} {content.strip()[:60]!r}", flush=True)
    print(f"SCORE {a.label}: {ok}/{len(Q)}")

if __name__ == "__main__":
    main()
