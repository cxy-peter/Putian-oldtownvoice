#!/usr/bin/env python3
"""Stage e-dialect JSON exports for human review. No network, audio download or training.

Only run this on exports you are entitled to process. The software does not grant
rights in source data. Generated JSONL is a candidate inventory, NOT a training set.
Python 3.10+, standard library only.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 25 * 1024 * 1024


def load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input is too large; split the authorized export first.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def identifier(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("Boolean is not an ID.")
    s = str(value) if isinstance(value, (str, int)) else ""
    if not s.isascii() or not s.isdecimal() or len(s) > 30:
        raise ValueError("Expected a numeric source ID.")
    return str(int(s))


def string(value: Any, limit: int = 8000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Unexpected text type or length.")
    return value.strip()


def mandarin_values(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        # Source uses a serialized list internally; never reproduce its eval().
        # Accept JSON arrays or a simple text label. Reject Python-list expressions.
        if value.lstrip().startswith("["):
            value = json.loads(value)
        else:
            value = [value]
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Unexpected Mandarin-label format.")
    return list(dict.fromkeys(string(item, 1000) for item in value if string(item, 1000)))


def rows(value: Any, kind: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        result = value
    elif isinstance(value, dict):
        if kind == "words":
            result = value.get("result", [value["word"]] if "word" in value else None)
        else:
            result = value.get("pronunciation")
    else:
        result = None
    if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
        raise ValueError(f"Unrecognized {kind} export shape.")
    return result


def normalize(words_json: Any, pronunciations_json: Any, source_base: str,
              reviews: dict[str, Any] | None = None) -> tuple[list, list, dict]:
    """Join by pronunciation.word_id, never by word.source or identical IPA."""
    u = urlsplit(source_base)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("source_base must be an HTTPS origin/base without credentials or queries.")
    reviews = reviews or {}
    if not isinstance(reviews, dict):
        raise ValueError("Reviews must be keyed by pronunciation ID.")
    word_rows = rows(words_json, "words")
    pron_rows = rows(pronunciations_json, "pronunciations")
    words: dict[str, dict] = {}
    for w in word_rows:
        wid = identifier(w.get("id"))
        if wid in words:
            raise ValueError("Duplicate Word ID; inspect/merge the source exports explicitly.")
        words[wid] = w
    candidates, quarantine = [], []
    seen: set[str] = set()
    for index, wrapper in enumerate(pron_rows):
        pid = None
        try:
            p = wrapper.get("pronunciation", wrapper)
            if not isinstance(p, dict):
                raise ValueError("Malformed pronunciation object.")
            pid = identifier(p.get("id"))
            if pid in seen:
                raise ValueError("Duplicate pronunciation ID.")
            seen.add(pid)
            wid = identifier(p.get("word_id"))
            if wid not in words:
                raise ValueError("Referenced Word was not supplied; no IPA-based fallback is allowed.")
            w = words[wid]
            if p.get("visibility") is not True or w.get("visibility") is False:
                raise ValueError("Not explicitly a visible pronunciation/word.")
            source = string(p.get("source"), 4096)
            s = urlsplit(source)
            if s.scheme not in ("http", "https") or not s.hostname or s.username or s.password:
                raise ValueError("Missing or invalid media reference.")
            review = reviews.get(pid, {})
            if not isinstance(review, dict):
                raise ValueError("Malformed local review.")
            media_kind = review.get("audio_kind", "unknown")
            if media_kind not in ("unknown", "human", "synthetic", "concatenated"):
                raise ValueError("Unknown audio_kind.")
            target = string(review.get("mandarin"), 2000)
            permission = review.get("permissions", {})
            if not isinstance(permission, dict):
                raise ValueError("Malformed permissions record.")
            evidence = string(permission.get("evidence"), 2000)
            blockers = ["audio_not_downloaded_or_acoustically_validated"]
            if media_kind != "human":
                blockers.append("not_verified_human_audio")
            if review.get("meaning_reviewed") is not True or not target:
                blockers.append("mandarin_meaning_not_reviewed")
            if permission.get("training") is not True or not evidence:
                blockers.append("training_permission_not_recorded")
            if not review.get("speaker_id"):
                blockers.append("speaker_id_unknown_contributor_is_not_speaker")
            if s.scheme == "http":
                blockers.append("media_transport_is_http_do_not_auto_upgrade_or_download")
            # Do not carry usernames, avatars or contact details into the corpus.
            item = {
                "schema_version": "1.0", "source": "e-dialect/hinghwa-dict-backend",
                "word_id": wid, "pronunciation_id": pid,
                "source_page": f"{source_base.rstrip('/')}/words/{wid}",
                "dialect": "莆仙话（源站标签；地区仍须核对）",
                "word": string(w.get("word"), 1000),
                "definition": string(w.get("definition")),
                "mandarin_candidates": mandarin_values(w.get("mandarin")),
                "mandarin_reviewed": target if review.get("meaning_reviewed") is True else None,
                "ipa": string(p.get("ipa"), 1000), "pinyin": string(p.get("pinyin"), 1000),
                "county": string(p.get("county"), 200), "town": string(p.get("town"), 200),
                "audio_source": source, "audio_kind": media_kind, "audio_path": None,
                "speaker_id": string(review.get("speaker_id"), 100) or None,
                "site_granted_flag": p.get("granted") is True,
                "permissions": {"training": permission.get("training") is True,
                                "redistribution": permission.get("redistribution") is True,
                                "evidence": evidence or None},
                "training_ready": False, "blocking_reasons": blockers,
                "note": "Candidate metadata only. Site approval does not establish permission or semantic correctness.",
            }
            candidates.append(item)
        except (ValueError, TypeError, json.JSONDecodeError):
            # Never echo raw payloads, credential-bearing URLs, or contributor data.
            quarantine.append({"row": index, "pronunciation_id": pid,
                               "reason": "invalid_or_nonpublic_pair; inspect the private source export locally"})
    audit = {"words_received": len(word_rows), "pronunciations_received": len(pron_rows),
             "candidates": len(candidates), "quarantined": len(quarantine),
             "audio_files_downloaded": 0, "training_ready": 0,
             "fallback_word_source_used": False, "network_requests": 0}
    return candidates, quarantine, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=Path, required=True)
    parser.add_argument("--pronunciations", type=Path, required=True)
    parser.add_argument("--source-base", required=True, help="Verified source base supplied by the data provider")
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidates, quarantine, audit = normalize(load_json(args.words), load_json(args.pronunciations),
                                                 args.source_base,
                                                 load_json(args.reviews) if args.reviews else {})
        args.out.mkdir(parents=True, exist_ok=True)
        for name in ("candidates.jsonl", "quarantine.jsonl", "audit.json"):
            if (args.out / name).exists():
                raise ValueError("Output exists; choose a new output directory to avoid overwriting reviews.")
        for name, values in (("candidates.jsonl", candidates), ("quarantine.jsonl", quarantine)):
            (args.out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in values), encoding="utf-8")
        (args.out / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False))
    except (OSError, ValueError, TypeError):
        parser.exit(1, "导入未完成：请检查本地文件、JSON结构、HTTPS来源和输出目录；没有下载音频或提交数据。\n")


if __name__ == "__main__":
    main()
