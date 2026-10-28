"""Measure /ops-answer-scope extraction on a case with known right answers.

Usage: uv run python evals/run_extraction.py <case> [--server http://localhost:8787]

A case is a folder under evals/cases/ with case.json (tabs, their question IDs and gold answers)
and the merchant material. The case's merchant is fictional. The runner sends each tab to the app
server exactly as the skill would (no Google: the sheet is described in the request) and scores the
requests that come back:

  gold        each expected answer: equals / contains / contains_any / not_contains / empty; for a question
              the tab already answers (the tab's `current` answers): agrees (the material confirms it) or
              conflict (the material says something else)
  leaks       filled answers that carry words from the other track (forbidden_words)
  cross-track bank questions added to this tab that belong to another track (no_bank_additions_from)
  spurious    new questions whose closest bank question is already in the tab (should have been an answer)

Nothing is recorded: the server only saves a draft. Results go to evals/results/ (git-ignored).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

HEADER = ["id", "enum", "question", "answer", "notes", "options", "priority", "subsection", "channels", "pillars",
          "category", "platform", "found_by"]
ANSWER_COL = HEADER.index("answer")
STATUS_COL = len(HEADER) + 2  # the server appends source, confidence, status, ai_note after the header
CLOSEST = re.compile(r"closest bank question: (ID-\d{4,})")


def load_case(name: str) -> dict:
    folder = Path(__file__).parent / "cases" / name
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    case["material"]["text"] = (folder / case["material"]["file"]).read_text(encoding="utf-8")
    case["name"] = name
    return case


def run_tab(server: str, case: dict, tab: dict) -> dict:
    ids = tab["ids"]
    current = tab.get("current", {})  # answers already in the tab, as after an earlier call
    material = {"label": case["material"]["label"], "kind": case["material"]["kind"], "text": case["material"]["text"]}
    if case["material"].get("date"):
        material["date"] = case["material"]["date"]
    body = {
        "sheet_id": f"EVAL-{case['name']}-{int(time.time())}",
        "merchant_name": case["merchant"],
        "tab_title": tab["name"],
        "tab_sheet_id": 7,
        "column_count": len(HEADER),
        "row_count": len(ids) + 1,
        "header_row": HEADER,
        "id_column": ["id"] + ids,
        "columns": {"answer": ["answer"] + [current.get(i, "") for i in ids]},
        "material": [material],
    }
    res = httpx.post(f"{server}/answers/jobs", json=body, params={"wait": 40}, timeout=90)
    data = res.json()
    while res.status_code == 200 and data.get("pending"):
        res = httpx.get(f"{server}/answers/jobs/{data['job_id']}", params={"wait": 40}, timeout=90)
        data = res.json()
    if res.status_code != 200:
        sys.exit(f"{tab['name']}: the app server refused the run (HTTP {res.status_code}): {res.text[:500]}")
    return data


def read_back(data: dict, ids: list[str]) -> tuple[dict[str, str], list[dict], dict[str, str]]:
    """The answers the batch would write, by ID, the Suggested additions rows, and the status the batch
    sets on rows that already had an answer (confirmed or conflict), by ID."""
    id_column = ["id"] + ids
    answers: dict[str, str] = {}
    additions: list[dict] = []
    statuses: dict[str, str] = {}
    for req in data["requests"]:
        cells = req.get("updateCells")
        if not cells:
            continue
        rng = cells["range"]
        if rng["startColumnIndex"] == ANSWER_COL and rng["endColumnIndex"] == ANSWER_COL + 1 and rng["startRowIndex"] < len(id_column):
            value = cells["rows"][0]["values"][0].get("userEnteredValue", {})
            answers[id_column[rng["startRowIndex"]]] = str(value.get("stringValue", value.get("numberValue", "")))
        elif rng["startColumnIndex"] <= STATUS_COL < rng["endColumnIndex"] and rng["startRowIndex"] < len(id_column) \
                and rng["startColumnIndex"] != 0:
            value = cells["rows"][0]["values"][STATUS_COL - rng["startColumnIndex"]].get("userEnteredValue", {})
            if value.get("stringValue") in ("confirmed", "conflict"):
                statuses[id_column[rng["startRowIndex"]]] = value["stringValue"]
        elif rng["startColumnIndex"] == 0 and rng["startRowIndex"] >= len(id_column):
            for row in cells["rows"]:
                values = row["values"]
                cell = lambda i: (values[i].get("userEnteredValue", {}) if i < len(values) else {})  # noqa: E731
                row_id = cell(0).get("stringValue")
                if row_id:
                    note = cell(16).get("stringValue", "") or ""
                    found = CLOSEST.search(note)
                    additions.append({"id": row_id, "question": cell(2).get("stringValue", ""),
                                      "answer": str(cell(3).get("stringValue", cell(3).get("numberValue", "")) or ""),
                                      "closest_id": found.group(1) if found else None})
    return answers, additions, statuses


def check(rule: dict, actual: str, agreed: set[str] = frozenset(), conflicts: set[str] = frozenset(),
          qid: str = "") -> tuple[bool, str]:
    if rule.get("agrees"):
        if qid in conflicts:
            return (False, "expected the material to agree; it was read as a conflict")
        return (qid in agreed, "" if qid in agreed else "expected the material to agree; it said nothing")
    if rule.get("conflict"):
        if qid in agreed:
            return (False, "expected a conflict; the material was read as agreeing")
        return (qid in conflicts, "" if qid in conflicts else "expected a conflict; the material said nothing")
    if rule.get("empty"):
        return (actual == "", "expected empty")
    if actual == "":
        return (False, "expected an answer, got none")
    if "equals" in rule and actual.strip() != rule["equals"]:
        return (False, f"expected {rule['equals']!r}")
    for word in rule.get("contains", []):
        if word.lower() not in actual.lower():
            return (False, f"missing {word!r}")
    if "contains_any" in rule and not any(w.lower() in actual.lower() for w in rule["contains_any"]):
        return (False, f"none of {rule['contains_any']}")
    for word in rule.get("not_contains", []):
        if word.lower() in actual.lower():
            return (False, f"must not contain {word!r}")
    return (True, "")


def score_tab(case: dict, tab: dict, data: dict) -> dict:
    answers, additions, statuses = read_back(data, tab["ids"])
    summary = data.get("summary", {})
    # agreement shows as a `confirmed` status on the row (and as agreed_ids on newer servers)
    agreed = set(summary.get("agreed_ids", [])) | {q for q, s in statuses.items() if s == "confirmed"}
    conflicts = {c["id"] for c in summary.get("conflicts", [])} | {q for q, s in statuses.items() if s == "conflict"}
    gold = tab["gold"]
    results = {}
    for qid, rule in gold.items():
        ok, why = check(rule, answers.get(qid, ""), agreed, conflicts, qid)
        actual = answers.get(qid, "") or next((c["found"] for c in summary.get("conflicts", []) if c["id"] == qid), "")
        results[qid] = {"ok": ok, "why": why, "actual": actual}
    expected_filled = [q for q, r in gold.items() if not r.get("empty")]
    leaks = {qid: a for qid, a in answers.items() if any(w.lower() in a.lower() for w in tab.get("forbidden_words", []))}
    bank_additions = [a for a in additions if not a["id"].startswith("NEW-")]
    new_questions = [a for a in additions if a["id"].startswith("NEW-")]
    cross_track = [a["id"] for a in bank_additions if a["id"] in set(tab.get("no_bank_additions_from", []))]
    # a new question is spurious when the material answers a bank question the case names as covering it
    spurious = [a for a in new_questions if a["closest_id"] in set(case.get("covered_by_bank", []))]
    passed = sum(1 for r in results.values() if r["ok"])
    return {
        "tab": tab["name"],
        "model": data.get("summary", {}).get("model"),
        "filled": len(answers),
        "agreed": sorted(agreed),
        "conflicts": sorted(conflicts),
        "gold_checks": len(gold),
        "gold_passed": passed,
        "expected_filled": len(expected_filled),
        "hit_filled": sum(1 for q in expected_filled if results[q]["ok"]),
        "failures": {q: r for q, r in results.items() if not r["ok"]},
        "leaks": leaks,
        "cross_track_additions": cross_track,
        "spurious_new_questions": [{"question": a["question"], "closest_id": a["closest_id"]} for a in spurious],
        "new_questions": [a["question"] for a in new_questions],
        "answers": answers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("--server", default="http://localhost:8787")
    args = parser.parse_args()
    case = load_case(args.case)
    report = {"case": args.case, "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "tabs": []}
    for tab in case["tabs"]:
        data = run_tab(args.server, case, tab)
        report["tabs"].append(score_tab(case, tab, data))
    out = Path(__file__).parent / "results" / f"{args.case}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'tab':4} {'filled':>6} {'agreed':>6} {'confl':>5} {'gold ok':>8} {'expected hit':>13} {'leaks':>5} {'cross':>5} {'spurious':>8}")
    for t in report["tabs"]:
        print(f"{t['tab']:4} {t['filled']:>6} {len(t['agreed']):>6} {len(t['conflicts']):>5} {t['gold_passed']:>3}/{t['gold_checks']:<4} "
              f"{t['hit_filled']:>6}/{t['expected_filled']:<6} "
              f"{len(t['leaks']):>5} {len(t['cross_track_additions']):>5} {len(t['spurious_new_questions']):>8}")
    for t in report["tabs"]:
        print(f"\n[{t['tab']}] model {t['model']}")
        for q, r in t["failures"].items():
            print(f"  fail {q}: {r['why']} (got {r['actual'][:70]!r})")
        for q, a in t["leaks"].items():
            print(f"  leak {q}: {a[:80]!r}")
        for q in t["cross_track_additions"]:
            print(f"  cross-track addition: {q}")
        for s in t["spurious_new_questions"]:
            print(f"  spurious new question (bank has {s['closest_id']}): {s['question'][:80]}")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
