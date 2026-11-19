#!/usr/bin/env python3
"""Which posts are due right now? Prints "reel", "story", both, or nothing.

GitHub's "schedule" is best effort: runs come 2-3 hours late or not at all. So post-reel.yml is started every hour and asks
this script. A post is DUE when the latest slot of that kind (India time) has passed and nothing of that kind was posted since.
"Posted" is read from the git history of ig/posted.json (commit messages "Instagram: mark reel/story as posted").

    reel slots  08:00  13:00  19:30 IST
    story slots 09:30  14:30  21:00 IST

    python tools/due_kinds.py [--now 2026-11-19T21:15]    # --now is for testing (India time)
"""
import argparse
import datetime as dt
import subprocess

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SLOTS = {"reel": [(8, 0), (13, 0), (19, 30)], "story": [(9, 30), (14, 30), (21, 0)]}


def last_post(kind):
    out = subprocess.run(["git", "log", "-1", "--format=%ct", f"--grep=mark {kind} as posted"],
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out else 0


def latest_slot(kind, now):
    cands = []
    for day in (now.date() - dt.timedelta(days=1), now.date()):
        for h, m in SLOTS[kind]:
            s = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
            if s <= now:
                cands.append(s)
    return max(cands)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", default="")
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.now).replace(tzinfo=IST) if a.now else dt.datetime.now(IST)
    due = []
    for kind in ("reel", "story"):
        slot = latest_slot(kind, now)
        lp = last_post(kind)
        if lp < slot.timestamp():
            due.append(kind)
        print(f"{kind}: latest slot {slot:%a %H:%M} IST, last post {dt.datetime.fromtimestamp(lp, IST):%a %d %H:%M} IST -> "
              f"{'DUE' if kind in due else 'done'}", file=__import__('sys').stderr)
    print(" ".join(due))


if __name__ == "__main__":
    main()
