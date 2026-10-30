"""python -m evals [--real] [--only ID,ID] [--json report.json] [--md report.md]"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from evals.harness import real_provider_available, run_mock, run_real
from evals.scenarios import SCENARIOS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    ap.add_argument("--real", action="store_true", help="use the AI provider keys in the environment / .env")
    ap.add_argument("--only", default="", help="comma-separated scenario ids or categories")
    ap.add_argument("--json", default="", help="write results as JSON here")
    ap.add_argument("--md", default="", help="write a markdown table here")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    picked = [s for s in SCENARIOS if not a.only or s.id in a.only.split(",") or s.category in a.only.split(",")]
    mode = "real" if a.real else "mock"
    if a.real:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        why = real_provider_available()
        if why:
            print(f"real-model run skipped: {why}")
            if a.json:
                with open(a.json, "w", encoding="utf-8") as fh:
                    json.dump({"mode": mode, "skipped": why, "results": []}, fh, indent=2)
            return 2
    results = []
    for sc in picked:
        r = (run_real if a.real else run_mock)(sc)
        results.append(r)
        if not a.quiet or not r.passed:
            mark = "skip" if r.skipped else ("PASS" if r.passed else "FAIL")
            print(f"{mark:4} {sc.id:20} [{sc.category}] caps={','.join(r.caps) or '-'} tools={r.offered} "
                  f"prompt={r.prompt_chars} {r.skipped}")
            for p in r.problems:
                print(f"       - {p}")
    ran = [r for r in results if not r.skipped]
    ok = sum(r.passed for r in ran)
    first = sum(r.first_try for r in ran)
    avg_tools = sum(r.offered for r in ran) / max(1, len(ran))
    print(f"\n{mode}: {ok}/{len(ran)} passed, {len(results) - len(ran)} skipped; routed first try {first}/{len(ran)}; "
          f"avg tools offered {avg_tools:.1f}")
    by = Counter()
    good = Counter()
    for r in ran:
        by[r.category] += 1
        good[r.category] += r.passed
    print("  " + ", ".join(f"{c} {good[c]}/{by[c]}" for c in sorted(by)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"mode": mode, "passed": ok, "ran": len(ran), "results": [r.as_dict() for r in results]}, fh, indent=2)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(f"| scenario | category | result | capabilities | tools offered |\n|---|---|---|---|---|\n")
            for r in results:
                res = "skipped (" + r.skipped + ")" if r.skipped else ("pass" if r.passed else "FAIL: " + "; ".join(r.problems)[:200])
                fh.write(f"| {r.id} | {r.category} | {res} | {', '.join(r.caps)} | {r.offered} |\n")
    return 0 if ok == len(ran) else 1


if __name__ == "__main__":
    sys.exit(main())
