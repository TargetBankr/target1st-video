# Series: 30 days x 2 videos (HSSC Group D + SSC), 50 questions each

- `plan.json`  the 60 sets (day N = gdNN + sscNN). Edit a topic or its subtopics and run again with force.
- `ready/`     generated files: `<id>.json` (video), `<id>.title.txt` (title + description), `<id>.check.txt` (questions to spot-check)

Make them: Actions > **Make series videos** > Run workflow > days `1-6`.
Build one by hand: Actions > **Build quiz video** > file `series/ready/gd01.json`.
Local test with no network: `python tools/make_series.py --days 1-2 --fake --out-dir /tmp/x`.
