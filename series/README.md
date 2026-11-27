# Series: 30 days x 2 videos (HSSC Group D + SSC), 50 questions each

- `plan.json`  the 60 sets (day N = gdNN + sscNN). Edit a topic or its subtopics and run again with force.
- `ready/`     generated files: `<id>.json` (video), `<id>.title.txt` (title + description), `<id>.check.txt` (questions to spot-check)

Every question is checked with Google Search; unconfirmed ones are dropped and replaced. About 10-15 min per set, so run about 5 days (10 sets) at a time.
Make them: Actions > **1A · Make JSON with Gemini (series)** > days `1-6`, mode `make + build`.
Build sets made earlier: same workflow, mode `build only`.
Reels/stories: set `auto_reels` / `auto_stories` to true in `base_meta.json` (off now).
Local test with no network: `python tools/make_series.py --days 1-2 --fake --out-dir /tmp/x`.
