#!/usr/bin/env python
"""Evaluate TTS quality by transcribing clips and scoring against reference.

Reads eval/manifest.json: {"items": [{"id": "...", "ref": "...", "mp3": "..."}]}
For each item, transcribes the mp3 with faster-whisper (medium, int8), then
scores similarity (word-level difflib ratio) against the Vietnamese reference.
Writes eval_report.json and prints a table, sorted worst-first.
"""
import difflib
import json
import os
import re
import sys

from faster_whisper import WhisperModel


def norm(t):
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def ratio(a, b):
    return difflib.SequenceMatcher(None, norm(a).split(), norm(b).split()).ratio()


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "eval"
    man = json.load(open(os.path.join(base, "manifest.json"), encoding="utf-8"))
    items = man["items"]
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    rows = []
    for it in items:
        mp3 = os.path.join(base, it["mp3"])
        segs, _ = model.transcribe(mp3, language="vi", vad_filter=False)
        hyp = " ".join(s.text.strip() for s in segs)
        sc = ratio(it["ref"], hyp)
        rows.append({"id": it["id"], "ref": it["ref"], "hyp": hyp,
                     "score": round(sc, 3)})
        print(f'{sc:4.2f}  {it["id"]}\n      REF: {it["ref"]}\n      HYP: {hyp}',
              flush=True)
    rows.sort(key=lambda r: r["score"])
    json.dump(rows, open(os.path.join(base, "eval_report.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    avg = sum(r["score"] for r in rows) / max(1, len(rows))
    print(f"\nAVG {avg:.3f}  n={len(rows)}", flush=True)
    print("WORST:")
    for r in rows[:10]:
        print(f'{r["score"]:.2f} {r["id"]}', flush=True)


if __name__ == "__main__":
    main()
