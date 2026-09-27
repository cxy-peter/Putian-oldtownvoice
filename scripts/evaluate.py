"""Offline CER from manually reviewed reference vs raw ASR, never from polished translations.
Usage: python scripts/evaluate.py predictions.jsonl
Rows: {"reference":"...","hypothesis":"...","speaker":"s1","split":"test"}
Reports uncertainty honestly: no test rows => no accuracy claim.
"""
import json
import sys
import unicodedata
from pathlib import Path

def normalize(s):
    return "".join(c.lower() for c in unicodedata.normalize("NFKC", s) if not unicodedata.category(c).startswith(("P", "Z")) and not c.isspace())

def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(x != y)))
        previous = current
    return previous[-1]

def evaluate(rows):
    errors = chars = 0
    speakers, groups = set(), {}
    count = 0
    for row in rows:
        speaker = row["speaker"]
        if speaker in groups and groups[speaker] != row["split"]:
            raise ValueError("Speaker leakage across splits")
        groups[speaker] = row["split"]
        if row["split"] != "test":
            continue
        ref, hyp = normalize(row["reference"]), normalize(row["hypothesis"])
        if not ref:
            continue
        errors += distance(ref, hyp)
        chars += len(ref)
        count += 1
        speakers.add(speaker)
    return {"test_utterances": count, "test_speakers": len(speakers), "reference_characters": chars,
            "character_errors": errors, "cer": errors/chars if chars else None,
            "note": "CER can exceed 100%. No translation scoring; no fabricated confidence interval or accuracy."}

if __name__ == "__main__":
    data = [json.loads(s) for s in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if s.strip()]
    print(json.dumps(evaluate(data), ensure_ascii=False, indent=2))
