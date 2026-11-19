#!/usr/bin/env python3
"""Make Instagram STORIES from reels that are already built (GitHub releases), one click, nothing is rebuilt or re-voiced.

For every reel release a story is cut out of the finished reel video:
    hook intro + ONE question (question, options, countdown, answer, points) + the QR promo (notes + mocks)
It is under 60 s (Instagram's limit for stories). If the first question makes it too long, the next question that fits is used.
Cut points come from the chapter list in the release's description file; each cut is then snapped to the exact slide change
(the chapter times are whole seconds only).

The story is saved as a new release  <reel tag>-story  with  <name>-story.mp4  and  <name>-story-caption.txt.
"-story" in the tag is how tools/ig_publish.py knows to post it as a story (video only: the API cannot add link stickers,
the QR codes are in the video). Stories are posted oldest first, in the order they were made here.

    python tools/make_stories.py                   # all reels that have no story yet and are not posted yet
    python tools/make_stories.py --include-posted  # also reels that were already posted
    python tools/make_stories.py --limit 5         # only the 5 oldest
    python tools/make_stories.py --tag video-12-x  # one reel
    python tools/make_stories.py --dry-run         # cut and report, create no releases
    python tools/make_stories.py --local reel.mp4 description.txt story.mp4   # cut one local file (testing)
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_SECS = 58.0          # Instagram: 3-60 s, keep a margin


def sh(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def parse_chapters(text):
    """'Chapters:' lines of description.txt -> [(seconds, name)]."""
    out, on = [], False
    for line in text.splitlines():
        if line.strip().lower().startswith("chapters"):
            on = True
            continue
        m = re.match(r"\s*(\d+):(\d{2})(?::(\d{2}))?\s+(.+?)\s*$", line) if on else None
        if m:
            a, b, c, name = m.groups()
            t = int(a) * 60 + int(b) if c is None else int(a) * 3600 + int(b) * 60 + int(c)
            out.append((float(t), name))
    return out


def duration(video):
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)).stdout.strip())


def snap(video, t_floor, total):
    """Chapter times are floored to whole seconds, so the real slide change is in [t, t+1). Find it as the frame with the biggest
    picture change in that window; fall back to the middle of the window."""
    ws = max(0.0, t_floor - 0.25)
    p = sh("ffmpeg", "-v", "error", "-ss", f"{ws:.3f}", "-t", "1.7", "-i", str(video), "-an",
           "-vf", "scale=270:-2,select='gte(scene,0)',metadata=print:file=-", "-f", "null", "-", check=False)
    best, best_t, cur_t = 0.0, None, None
    for line in p.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            cur_t = float(m.group(1))
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and cur_t is not None and float(m.group(1)) > best:
            best, best_t = float(m.group(1)), cur_t
    if best_t is not None and best >= 0.12:
        return min(total, ws + best_t)
    return min(total, t_floor + 0.5)


def plan(chapters, total, video, max_secs=MAX_SECS):
    """Pick the first question that makes intro + question + promo fit. Returns (segments, info) or raises ValueError."""
    names = [n for _, n in chapters]
    qidx = [i for i, n in enumerate(names) if re.fullmatch(r"Q\d+", n)]
    if not qidx or names[0] != "Intro":
        raise ValueError("no Intro/Q chapters in the description (not a quiz reel?)")
    if "Notes and mocks" not in names:
        raise ValueError("this reel has no QR promo part, so there is nothing to add after the question")
    pi = names.index("Notes and mocks")
    pend_i = names.index("Outro") if "Outro" in names else None
    p_start = snap(video, chapters[pi][0], total)
    p_end = snap(video, chapters[pend_i][0], total) if pend_i is not None else total
    if p_end - p_start < 3:
        raise ValueError("the QR promo part is missing or too short in this reel")
    intro_end = snap(video, chapters[qidx[0]][0], total)
    for q in qidx:
        q_start = intro_end if q == qidx[0] else snap(video, chapters[q][0], total)
        nxt = chapters[q + 1][0] if q + 1 < len(chapters) else total
        q_end = snap(video, nxt, total) if q + 1 < len(chapters) else total
        if q_end > p_start:
            q_end = p_start
        length = (intro_end - 0) + (q_end - q_start) + (p_end - p_start)
        if length <= max_secs:
            segs = [(0.0, intro_end)] + ([(q_start, q_end)] if q_start >= intro_end else []) + [(p_start, p_end)]
            segs = [(a, b) for a, b in segs if b - a > 0.05]
            return segs, {"question": names[q], "length": sum(b - a for a, b in segs)}
    raise ValueError(f"no question makes a story under {max_secs:.0f} s (intro + question + promo too long)")


def cut(video, desc_text, out, max_secs=MAX_SECS):
    total = duration(video)
    chapters = parse_chapters(desc_text)
    segs, info = plan(chapters, total, video, max_secs)
    parts, labels = [], ""
    for k, (a, b) in enumerate(segs):
        d = b - a
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{k}];"
                     f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.03,afade=t=out:st={max(0.0, d - 0.03):.3f}:d=0.03[a{k}]")
        labels += f"[v{k}][a{k}]"
    fg = ";".join(parts) + f";{labels}concat=n={len(segs)}:v=1:a=1[v][a]"
    sh("ffmpeg", "-y", "-v", "error", "-i", str(video), "-filter_complex", fg, "-map", "[v]", "-map", "[a]",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart", str(out))
    real = duration(out)
    if real > 60:
        raise ValueError(f"cut came out {real:.1f} s, over Instagram's 60 s")
    return info["question"], real


def gh_json(*args):
    return json.loads(sh("gh", *args).stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-posted", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=float, default=MAX_SECS)
    ap.add_argument("--local", nargs=3, metavar=("VIDEO", "DESC", "OUT"))
    a = ap.parse_args()

    if a.local:
        q, secs = cut(a.local[0], Path(a.local[1]).read_text(encoding="utf-8"), a.local[2], a.max)
        print(f"story from {q}: {secs:.1f} s -> {a.local[2]}")
        return

    rel = sorted(gh_json("release", "list", "--limit", "300", "--json", "tagName,createdAt"), key=lambda r: r["createdAt"])
    all_tags = {r["tagName"] for r in rel}
    try:
        posted = set(json.loads(Path("ig/posted.json").read_text(encoding="utf-8")))
    except Exception:
        posted = set()
    todo = []
    for r in rel:
        t = r["tagName"]
        if "-story" in t or f"{t}-story" in all_tags:
            continue
        if a.tag and t != a.tag:
            continue
        if not a.tag and t in posted and not a.include_posted:
            continue
        todo.append(t)
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(todo)} reel(s) to turn into stories")
    ok, skipped = 0, []
    for t in todo:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            try:
                assets = [x["name"] for x in gh_json("release", "view", t, "--json", "assets")["assets"]]
            except subprocess.CalledProcessError:
                skipped.append((t, "release not readable"))
                continue
            vid = next((x for x in assets if x.endswith(".mp4")), None)
            des = next((x for x in assets if x.endswith("-description.txt")), None)
            if not (vid and des and any(x.endswith("-caption.txt") for x in assets)):
                skipped.append((t, "not a reel release (needs .mp4, -description.txt and -caption.txt)"))
                continue
            sh("gh", "release", "download", t, "--pattern", vid, "--pattern", des, "--dir", str(td), "--clobber")
            name = vid[:-4]
            out = td / f"{name}-story.mp4"
            try:
                q, secs = cut(td / vid, (td / des).read_text(encoding="utf-8"), out, a.max)
            except (ValueError, subprocess.CalledProcessError) as e:
                msg = e.stderr[-300:] if isinstance(e, subprocess.CalledProcessError) else str(e)
                skipped.append((t, msg))
                print(f"SKIP {t}: {msg}")
                continue
            print(f"{t}: story from {q}, {secs:.1f} s")
            if a.dry_run:
                ok += 1
                continue
            cap = td / f"{name}-story-caption.txt"
            cap.write_text("story (video only, no caption)", encoding="utf-8")
            sh("gh", "release", "create", f"{t}-story", str(out), str(cap),
               "--title", f"{name} story", "--notes", "Instagram story cut from the reel: hook + one question + QR promo. Posted by Post reel to Instagram.")
            ok += 1
    print(f"\nDone: {ok} stories {'checked (dry run)' if a.dry_run else 'made'}, {len(skipped)} skipped")
    for t, why in skipped:
        print(f"  skipped {t}: {why}")
    out_f = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if out_f:
        with open(out_f, "a", encoding="utf-8") as f:
            f.write(f"Stories {'checked' if a.dry_run else 'made'}: **{ok}**, skipped: {len(skipped)}\n")
            for t, why in skipped:
                f.write(f"- {t}: {why}\n")


if __name__ == "__main__":
    main()
