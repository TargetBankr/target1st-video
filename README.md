# Target1st video

The repo does 3 things.

## 1 · Get the JSON

- **Manual:** make it in the PDF tool (app-tcl-101 > Export Video JSON), name it `<name>.done.json`, and upload it into the `jsons/` folder.
- **Gemini:**
  - Actions > **1A · Make JSON with Gemini (series)**: HSSC Group D + SSC 50-question sets. The files go to `series/ready/`.
  - Actions > **1B · Make JSON with Gemini (daily current affairs)**: a nightly news quiz. It's paused while the repo variable `DAILY_CA_PAUSED` is `true`.

## 2 · Build: YouTube video + reels + stories

Uploading a `.done.json` file starts **2 · Build video + reels + stories** by itself.

1. The YouTube video is built and put in **Releases**. Download the `.mp4` and the `-description.txt` file, then upload them to YouTube yourself.
2. If **Auto Instagram** is set to on in the PDF tool (meta `auto_reels: true`), the reels and stories are made from the same questions and built straight after. The voice is reused from the cache.

Old JSONs that don't have the switch only make the YouTube video. If you want reels from an old JSON, use Actions > **Extra · Make reels from an old JSON**.

## 3 · Post to Instagram

**3 · Post to Instagram** runs every hour and posts finished reels and stories in these slots (India time):
- Reels: 8:00, 13:00, 19:30
- Stories: 9:30, 14:30, 21:00

Repo variables (Settings > Secrets and variables > Actions > Variables):
- `SCHEDULED_POSTING = true` turns timed posting on.
- `IG_PAUSED = true` stops all posting.

YouTube upload is always done by hand.

## Folders

| Path | What |
|---|---|
| `jsons/` | your manual JSONs |
| `series/` | the Gemini series plan (`plan.json`, `base_meta.json`) and the made sets (`ready/`) |
| `daily/` | current affairs files |
| `reels/` | reel and story JSONs (made by the workflow, don't edit them) |
| `build.py`, `fx.py` | the video builder |
| `tools/` | the reel maker, the Instagram poster and the Gemini makers |
| `assets/` | QR images, music |
| `ig/posted.json` | what has already been posted (the workflow updates it) |

Other workflows: **Tool · Delete files** (bulk delete, for example `jsons/*.done.json`) and **Tool · Refresh Instagram token** (runs by itself every 2 weeks).
