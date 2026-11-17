#!/usr/bin/env python3
"""Split one long quiz JSON into short Instagram-reel JSONs (9:16).

    python tools/make_reels.py questionshr25.done.json                 # 3 questions per reel, into reels/
    python tools/make_reels.py questionshr25.done.json --size 4 --out reels --suffix .done+after

Every reel JSON gets the same meta as the original (voice engine, speaker, pronounce list, keys...) plus:
    aspect: reel, a short hook intro and a "follow" outro, no filler lines, countdown 3, max 2 points per question
    title:  "<original title> · भाग 2"   (so every reel has its own caption)
Questions are copied untouched, so voice lines already made for the long video come out of the cache (no new credits).
A last reel that would hold a single question is merged into the one before it.

Push the files you want built (they are named <name>-r01.done.json ...). Several files in ONE commit build one after
another in file-name order, so r01, r02, r03 ... come out in order.

Options
    --size N        questions per reel (default 3, 0 = the whole set in ONE reel). Rough length: about 30-40 s per question.
    --out DIR       output folder (default reels)
    --suffix TEXT   ending of the file name before .json (default ".done"; use ".done+after" to also wait for earlier runs)
    --points N      points spoken and shown per question (default 2, 0 = all)
    --countdown N   seconds of thinking time after the options (default 3, 0 = none)
    --format quiz|revision   (default quiz: options, countdown, answer, points)
    --no-promo      leave out the notes + mock-test QR promo
    --first K --count M      only make reels K..K+M-1 (1-based), handy for a test batch
"""
import argparse
import json
import re
from pathlib import Path


HOOKS = [
    ("क्या आप इसका सही जवाब दे पाएँगे?", "{n} प्रश्न · जवाब सोचिए!"),
    ("पेपर में यही पूछा जा सकता है!", "{n} प्रश्न · जवाब सोचिए!"),
    ("90% लोग इसमें गलती करते हैं!", "{n} प्रश्न · खुद को परखिए!"),
    ("सिर्फ़ 1 मिनट में अपनी तैयारी जाँचिए!", "{n} प्रश्न · जवाब सोचिए!"),
    ("परीक्षा से पहले ये प्रश्न ज़रूर देख लें!", "{n} प्रश्न · जवाब सोचिए!"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_file")
    ap.add_argument("--size", type=int, default=3)
    ap.add_argument("--out", default="reels")
    ap.add_argument("--suffix", default=".done")
    ap.add_argument("--points", type=int, default=2)
    ap.add_argument("--countdown", type=int, default=3)
    ap.add_argument("--format", default="quiz", choices=["quiz", "revision"])
    ap.add_argument("--list-file", default="", help="also write the made file paths (one per line) into this file")
    ap.add_argument("--no-promo", action="store_true", help="no notes/mock-test QR promo before the outro")
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--count", type=int, default=0)
    a = ap.parse_args()
    if a.size < 0:
        ap.error("--size must be 0 (everything in one reel) or more")

    src = Path(a.json_file)
    data = json.loads(src.read_text(encoding="utf-8"))
    qs = data["questions"]
    base = re.sub(r"\.done.*\.json$|\.json$", "", src.name)

    chunks = [qs[i:i + a.size] for i in range(0, len(qs), a.size)] if a.size else [list(qs)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:
        chunks[-2] += chunks.pop()

    start = max(1, a.first) - 1
    end = start + a.count if a.count else len(chunks)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for k, chunk in enumerate(chunks, 1):
        if not (start < k <= end):
            continue
        meta = dict(data["meta"])
        title = str(meta.get("title", "")).strip()
        hook, small = HOOKS[(k - 1) % len(HOOKS)]
        small = small.format(n=len(chunk))
        meta.update({
            "aspect": "reel",
            "title": (f"{title} · भाग {k}" if title else f"भाग {k}") if len(chunks) > 1 else (title or "Target1st"),
            "format": a.format,
            "countdown": a.countdown,
            "max_points": a.points,
            "filler_lines": [],
            "intro": f"{hook} {title}। {len(chunk)} प्रश्न, जवाब सोचिए!" if title else f"{hook} {len(chunk)} प्रश्न, जवाब सोचिए!",
            "intro_show": hook,
            "intro_small": small,
            "promo": not a.no_promo,
            "outro": "रोज़ ऐसे प्रश्नों के लिए Target1st को फॉलो करें।",
            "outro_show": "फॉलो करें",
            "reel_of": f"{k}/{len(chunks)}",
        })
        path = out / f"{base}-r{k:02d}{a.suffix}.json"
        path.write_text(json.dumps({"meta": meta, "questions": chunk}, ensure_ascii=False, indent=1), encoding="utf-8")
        made.append((path, len(chunk)))

    print(f"{len(qs)} questions -> {len(chunks)} reel(s)" + (f" of about {a.size}" if a.size else "") + f"; wrote {len(made)} file(s) to {out}/")
    if a.list_file:
        Path(a.list_file).write_text("".join(f"{p}\n" for p, _ in made), encoding="utf-8")
    for p, n in made:
        print(f"  {p.name}  ({n} questions)")


if __name__ == "__main__":
    main()
