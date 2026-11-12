#!/usr/bin/env python3
"""Target1st quiz video builder.

questions.json -> voice (Edge-TTS or Gemini AI voice) -> HTML slides (Playwright screenshots) -> one MP4 (FFmpeg).

Usage:
    python build.py questions.json --out output [--limit 2] [--theme night] [--layout grid]
                                    [--format revision] [--tts gemini] [--fake-tts]

theme:  classic | night | royal
layout: list | grid        (how the 4 options look on the question slide)
format: quiz | revision    (both read the options aloud; quiz adds a countdown, revision has none)
tts:    edge | gemini | sarvam   (edge = Edge-TTS, free, unlimited; gemini = Gemini AI voice, free tier is slow/limited;
                                  sarvam = Sarvam Bulbul Hindi voice, Rs 100 free credits then paid)
Each of these can also be set in the JSON "meta"; command-line values win ("auto" = use the JSON).
Old names from earlier versions of the PDF tool are converted automatically
(dark -> night, light -> classic, maroon -> royal, standard -> quiz, short -> revision,
landscape/portrait -> list).

GEMINI VOICE
    Set meta "tts": "gemini" (or pass --tts gemini) and provide the GEMINI_API_KEY environment variable
    (GitHub: repository secret GEMINI_API_KEY, already wired in video.yml).
    Optional meta keys:
      gemini_voice  prebuilt voice name, default "Kore" (also Puck, Sulafat, Charon, Fenrir, Zephyr...)
      gemini_models list of model names, tried in order. When one hits its daily limit the next one is used.
                    Default ["gemini-3.1-flash-tts-preview", "gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]. Add more by copying the
                    exact model name from AI Studio ("Get code"). A name that does not exist is skipped, not fatal.
                    (old single key "gemini_model" still works)
      gemini_batch  questions per Gemini call, default 1 (raised to 2-3 by itself when the video needs more calls than
                    the daily limit of your models; meta gemini_auto_batch false = never do that). One call reads a whole question (question, options, answer,
                    points, trick) and the audio is cut back into lines at the pauses. Free tier allows only about
                    10 calls a day per model, so this is what makes a 25-question video possible. 2 = even fewer calls.
      gemini_style  optional style instruction put in front of the text, default none. Gemini sometimes READS it aloud,
                    so leave it empty unless you really need it.
      gemini_speed  default 1.3 (Gemini has no speed setting, FFmpeg speeds it up, pitch is kept; "rate" is Edge only)
      gemini_delay  seconds to wait between calls, default 21 (free tier allows 3 calls a minute per model)
    Calls run one at a time with retries. Every finished line is cached in <out>/work/audio, so a run stopped by
    the free daily limit can be re-run to continue (the cache is shared by all models). If every model has hit its
    daily limit the build stops cleanly with exit code 75 (video.yml sees this and resumes by itself after the
    quota resets, about 1:30 pm IST; every other failure exits with code 1).

SARVAM VOICE (Bulbul, built for Indian languages, Hindi = hi-IN)
    Set meta "tts": "sarvam" (or --tts sarvam) and provide the SARVAM_API_KEY environment variable
    (GitHub: repository secret SARVAM_API_KEY, wired in video.yml). New accounts get Rs 100 free credits.
    Optional meta keys:
      sarvam_model    default "bulbul:v3" (also "bulbul:v4-flash", cheaper; its speaker names differ, e.g. "ishita_hi_devotional")
      sarvam_speaker  default "shubh" (lowercase, must match the model; v3 also has aditya, ritu, priya, neha, rahul, pooja, ...)
      sarvam_pace     default 1.2, range 0.5-2.0 (Sarvam has its own speed control, "rate" is Edge only)
      sarvam_delay    seconds between calls, default 1 (limit is 60 requests/minute)
      sarvam_price_per_1000  Rs per 1,000 characters, only used for the cost line in the log (default 2)
      sarvam_max_credits     stop BEFORE spending if the estimate is higher than this (0 = no limit)
    Sarvam charges per character, not per call, so batching lines does not save anything. To spend less:
      lean_speech: true   shorter option/answer lines ("ए, यमुना।" instead of "ऑप्शन ए, यमुना।"), about 9% fewer characters
      max_points: 2       speak and show only the first 2 points of each question (about 14% fewer with 3 points)
    Every finished line is cached in <out>/work/audio, so a re-run never pays twice for the same line.

FILLER LINES (short spoken lines between questions, e.g. "अगर आप ध्यान दें, तो इसका जवाब आपको आता ही होगा।")
    meta "filler_lines": ["line 1", "line 2", ...]   12-15 lines work well; empty or missing = no fillers
    meta "filler_every": [3, 4]                      a filler comes after every 3rd or 4th question, chosen at random
                                                      (a single number like 3 means exactly every 3rd)
    meta "filler_seed":  "any text"                  optional; same seed = same placement every build (default: the title)
    A filler is spoken over the slide that is already on screen (no new slide). Lines are used in random order and
    none repeats until all have been used. No filler comes after the last question. Every filler is an ordinary
    voice line, so it is cached in <out>/work/audio like all others: once a line has been voiced it costs nothing
    (no Sarvam credits, no Gemini call) in any later video that uses the same line and the same voice settings.
"""
import argparse
import asyncio
import base64
import hashlib
import html
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

W, H, FPS = 1920, 1080, 30
QUOTA_EXIT = 75  # exit code meaning "every Gemini model is out of daily quota": video.yml waits and resumes
PAUSE_DEFAULT = 0.15  # silence kept after every spoken line, seconds (meta "pause" overrides)
TRIM = ("silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB,areverse")
LET_SAY = {"A": "ए", "B": "बी", "C": "सी", "D": "डी"}

SERIF = "'Noto Serif Devanagari','Noto Serif','FreeSerif','Lohit Devanagari',serif"
SANS = "'Noto Sans Devanagari','Noto Sans','FreeSans','Lohit Devanagari',sans-serif"

THEMES = {
    "classic": {"bg": "#ffffff", "fg": "#000000", "q": "#e00000", "rule": "#000000", "ans": "#0a7d2c",
                "ansfg": "#ffffff", "pt": "#111111", "wm": "rgba(0,0,0,.07)", "badgebg": "#000000",
                "badgefg": "#ffffff", "cd": "#e00000", "trickbg": "#fff3bf", "trickfg": "#3b2f00",
                "num": "#e00000", "font": SERIF},
    "night": {"bg": "#0f172a", "fg": "#f8fafc", "q": "#fbbf24", "rule": "#38bdf8", "ans": "#16a34a",
              "ansfg": "#ffffff", "pt": "#e2e8f0", "wm": "rgba(255,255,255,.06)", "badgebg": "#38bdf8",
              "badgefg": "#0f172a", "cd": "#fbbf24", "trickbg": "#1e293b", "trickfg": "#fde68a",
              "num": "#fbbf24", "font": SANS},
    "royal": {"bg": "#fdf6e3", "fg": "#2b1b0e", "q": "#7a1f2b", "rule": "#7a1f2b", "ans": "#1f6d3f",
              "ansfg": "#ffffff", "pt": "#2b1b0e", "wm": "rgba(122,31,43,.08)", "badgebg": "#7a1f2b",
              "badgefg": "#fdf6e3", "cd": "#7a1f2b", "trickbg": "#f3e2b3", "trickfg": "#4a2c0a",
              "num": "#7a1f2b", "font": SERIF},
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1920px;height:1080px;background:var(--bg);font-family:var(--font);font-weight:700;color:var(--fg);position:relative;overflow:hidden}
.wm{position:absolute;left:0;right:0;top:400px;text-align:center;font-size:230px;color:var(--wm);transform:rotate(-24deg);z-index:0}
.wrap{position:absolute;left:150px;right:150px;top:40px;z-index:1}
.head{border-top:12px solid var(--rule);border-bottom:12px solid var(--rule);text-align:center;font-size:68px;line-height:1.2;padding:14px 0}
.q{color:var(--q);font-size:68px;line-height:1.3;margin-top:46px}
.opts{margin-top:30px}
.opt{font-size:64px;line-height:1.2;padding:14px 0}
.opts.grid{display:grid;grid-template-columns:1fr 1fr;gap:26px 30px}
.opts.grid .opt{border:5px solid var(--rule);border-radius:18px;padding:22px 28px;font-size:58px}
.cd{position:absolute;right:170px;top:470px;width:240px;height:240px;border:16px solid var(--cd);border-radius:50%;font-size:140px;color:var(--cd);text-align:center;line-height:205px;z-index:2;background:var(--bg)}
.cd.g{top:790px;right:150px;width:200px;height:200px;border-width:14px;font-size:110px;line-height:168px}
.badge{display:inline-block;margin-top:30px;background:var(--badgebg);color:var(--badgefg);font-size:40px;padding:6px 28px;border-radius:10px}
.ans{margin-top:22px;background:var(--ans);color:var(--ansfg);font-size:64px;line-height:1.25;padding:18px 32px;border-radius:14px;display:flex;align-items:center;gap:22px}
.ans svg{flex:none}
.pts{margin-top:30px}
.pt{font-size:50px;line-height:1.35;padding:8px 0;color:var(--pt)}
.pt b{color:var(--num);margin-right:14px}
.trick{margin-top:40px;background:var(--trickbg);color:var(--trickfg);border-radius:18px;padding:34px 44px;font-size:62px;line-height:1.4}
.trick .lbl{display:block;font-size:42px;margin-bottom:12px;opacity:.85}
.center{margin-top:200px;text-align:center;font-size:78px;line-height:1.5}
.center small{display:block;font-size:50px;color:var(--q);margin-top:30px}
"""

CHECK = ('<svg width="70" height="70" viewBox="0 0 24 24"><path d="M4 12.5l5 5L20 6.5" '
         'stroke="currentColor" stroke-width="3.2" fill="none" stroke-linecap="round" '
         'stroke-linejoin="round"/></svg>')


def esc(t):
    return html.escape(str(t), quote=False)


def norm_point(p):
    if isinstance(p, str):
        return {"show": p, "say": p}
    return {"show": p["show"], "say": p.get("say", p["show"])}


def page_html(meta, qs, st, theme, layout, fmt):
    th = THEMES[theme]
    vars_css = ":root{" + "".join(f"--{k}:{v};" for k, v in th.items()) + "}"
    sub = f' — {esc(meta["subtitle"])}' if meta.get("subtitle") else ""
    head = f'<div class="head">{esc(meta["title"])}{sub}</div>'
    body = ""
    mode = st["mode"]
    if mode == "intro":
        cd = int(meta.get("countdown", 5))
        line = (f"हर प्रश्न के बाद {cd} सेकंड सोचने का समय" if fmt == "quiz" and cd
                else "हर प्रश्न का उत्तर और मुख्य पॉइंट्स")
        body = f'<div class="center">कुल {len(qs)} प्रश्न<small>{line}</small></div>'
    elif mode == "outro":
        body = (f'<div class="center">{esc(meta.get("outro_show", "देखने के लिए धन्यवाद!"))}'
                f'<small>{esc(meta.get("channel", "Target1st"))}</small></div>')
    elif mode == "q":
        q = qs[st["i"] - 1]
        body = f'<div class="q">{st["i"]}. {esc(q["q"])}</div>'
        if st.get("opts"):
            cls = "opts grid" if layout == "grid" else "opts"
            body += f'<div class="{cls}">' + "".join(
                f'<div class="opt">{l}) {esc(t)}</div>' for l, t in zip("ABCD", q["options"])
            ) + "</div>"
        if st.get("cd"):
            body += f'<div class="cd{" g" if layout == "grid" else ""}">{st["cd"]}</div>'
    elif mode == "answer":
        q = qs[st["i"] - 1]
        ans = q["answer"].strip().upper()
        idx = "ABCD".index(ans)
        body = (f'<div class="badge">प्रश्न {st["i"]}</div>'
                f'<div class="ans">{CHECK}<span>सही उत्तर: {ans}) {esc(q["options"][idx])}</span></div>'
                '<div class="pts">')
        for k, p in enumerate(q["points"][: st["pts"]], 1):
            body += f'<div class="pt"><b>{k}.</b>{esc(norm_point(p)["show"])}</div>'
        body += "</div>"
    elif mode == "trick":
        q = qs[st["i"] - 1]
        body = (f'<div class="badge">प्रश्न {st["i"]}</div>'
                f'<div class="trick"><span class="lbl">ट्रिक</span>{esc(norm_point(q["trick"])["show"])}</div>')
    return (f'<html><head><meta charset="utf-8"><style>{vars_css}{CSS}</style></head>'
            f'<body><div class="wm">Target1st</div><div class="wrap">{head}{body}</div></body></html>')


def plan_fillers(meta, n_questions):
    """Return {question number: filler line}. A filler is placed after question k, never after the last one.

    Gap between fillers is random inside meta "filler_every" (default [3, 4]). Lines come from a shuffled bag,
    so none repeats until every line has been used. The random generator is seeded (meta "filler_seed", else the
    title), so rebuilding the same video gives the same placement.
    """
    lines = [str(x).strip() for x in (meta.get("filler_lines") or []) if str(x).strip()]
    if not lines or n_questions < 2:
        return {}
    every = meta.get("filler_every", [3, 4])
    if isinstance(every, (int, float, str)):
        every = [every, every]
    lo = max(1, int(every[0]))
    hi = max(1, int(every[-1]))
    if hi < lo:
        lo, hi = hi, lo
    rng = random.Random(str(meta.get("filler_seed") or meta.get("title") or "target1st"))
    bag, last, plan = [], None, {}
    k = rng.randint(lo, hi)
    while k < n_questions:
        if not bag:
            bag = lines[:]
            rng.shuffle(bag)
            if last is not None and len(bag) > 1 and bag[0] == last:
                bag.append(bag.pop(0))
        last = bag.pop(0)
        plan[k] = last
        k += rng.randint(lo, hi)
    return plan


def make_steps(data, limit, fmt):
    meta = data["meta"]
    qs = data["questions"][:limit] if limit else data["questions"]
    fillers = plan_fillers(meta, len(qs))
    cd = int(meta.get("countdown", 5))
    lean = bool(meta.get("lean_speech", False))   # fewer spoken characters (cheaper voice): shorter option/answer lines
    max_pts = int(meta.get("max_points", 0))      # 0 = speak and show all points, 2 = only the first two
    intro = meta.get("intro") or ("नमस्कार दोस्तों! आज हम इस पेपर के प्रश्न हल करेंगे। "
                                  "हर प्रश्न के बाद सोचने का समय मिलेगा, फिर सही उत्तर और मुख्य पॉइंट्स बताए जाएंगे।"
                                  if fmt == "quiz" else
                                  "नमस्कार दोस्तों! आज हम इन प्रश्नों का तेज़ रिविज़न करेंगे। "
                                  "हर प्रश्न का सही उत्तर और उससे जुड़े मुख्य पॉइंट्स देखिए।")
    steps = [{"state": {"mode": "intro"}, "say": intro, "chapter": "Intro"}]
    for i, q in enumerate(qs, 1):
        opts = q["options"]
        ans = q["answer"].strip().upper()
        idx = "ABCD".index(ans)
        # both formats: question, then options shown and read aloud. Only quiz adds the countdown.
        steps.append({"state": {"mode": "q", "i": i, "opts": False}, "say": q["q"], "chapter": f"Q{i}"})
        say_opts = " ".join((f"{LET_SAY[l]}, {t}।" if lean else f"ऑप्शन {LET_SAY[l]}, {t}।")
                            for l, t in zip("ABCD", opts))
        steps.append({"state": {"mode": "q", "i": i, "opts": True}, "say": say_opts, "tight": True})
        if fmt == "quiz":
            for n in range(cd, 0, -1):
                steps.append({"state": {"mode": "q", "i": i, "opts": True, "cd": n}, "silence": 1.0})
        steps.append({"state": {"mode": "answer", "i": i, "pts": 0},
                      "say": (f"सही उत्तर {LET_SAY[ans]}, {opts[idx]}।" if lean
                              else f"सही उत्तर है, ऑप्शन {LET_SAY[ans]}, {opts[idx]}।")})
        for k, p in enumerate(q["points"][:max_pts] if max_pts else q["points"], 1):
            steps.append({"state": {"mode": "answer", "i": i, "pts": k}, "say": norm_point(p)["say"]})
        if q.get("trick"):
            steps.append({"state": {"mode": "trick", "i": i}, "say": "ट्रिक। " + norm_point(q["trick"])["say"]})
        if i in fillers:
            # spoken over the slide that is already on screen; the image is reused, so no new slide is rendered
            steps.append({"state": dict(steps[-1]["state"]), "say": fillers[i], "filler": True})
    outro =meta.get("outro") or ("तो दोस्तों, आज के लिए बस इतना ही। वीडियो पसंद आया हो तो लाइक करें "
                                  "और Target1st चैनल को सब्सक्राइब ज़रूर करें।")
    steps.append({"state": {"mode": "outro"}, "say": outro, "chapter": "Outro"})
    return qs, steps


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Command failed: {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r.stdout


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


GEMINI_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
GEMINI_VOICE = "Kore"
# No spoken instruction by default: Gemini TTS sometimes reads an instruction aloud ("Say in a clear Hindi teacher
# voice...") instead of obeying it. The voice name and the Hindi text are enough. Set meta "gemini_style" only if you
# accept that risk.
GEMINI_STYLE = ""


def gemini_tts_once(prompt, voice, model, out_wav, api_key):
    """One Gemini TTS call -> 24 kHz mono 16-bit WAV at out_wav. Raises on any failure."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        j = json.load(r)
    pcm = None
    for cand in j.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                pcm = base64.b64decode(inline["data"])
    if not pcm:
        raise RuntimeError(f"Gemini returned no audio: {json.dumps(j)[:300]}")
    tmp = out_wav.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    tmp.replace(out_wav)


def rate_ok(chars, seconds):
    """Normal Gemini Hindi runs at about 8-16 characters a second before speed-up. Far outside that means the
    clip is cut off, stretched, or has dead air, so it is not used."""
    return 4.0 <= chars / max(0.05, seconds) <= 26


def _nearest_gaps(gaps, chars, total):
    """Pick len(chars)-1 pauses, in order, that sit closest to where each line should end if every character took
    the same time, with a bonus for longer pauses (the gap between paragraphs is longer than a comma pause)."""
    n = len(chars)
    tot = sum(chars) or 1
    exp = [total * sum(chars[:k]) / tot for k in range(1, n)]
    mids = [(a + b) / 2 for a, b in gaps]
    cost = lambda k, j: abs(mids[j] - exp[k]) - 6.0 * (gaps[j][1] - gaps[j][0])
    m = len(gaps)
    INF = float("inf")
    best = [[INF] * m for _ in range(n - 1)]
    back = [[-1] * m for _ in range(n - 1)]
    for j in range(m):
        best[0][j] = cost(0, j)
    for k in range(1, n - 1):
        run_best, run_j = INF, -1
        for j in range(m):
            if j > 0 and best[k - 1][j - 1] < run_best:
                run_best, run_j = best[k - 1][j - 1], j - 1
            if run_j >= 0:
                best[k][j] = run_best + cost(k, j)
                back[k][j] = run_j
    j = min(range(m), key=lambda x: best[n - 2][x])
    if best[n - 2][j] == INF:
        return None
    pick = [j]
    for k in range(n - 2, 0, -1):
        j = back[k][j]
        pick.append(j)
    return [gaps[i] for i in reversed(pick)]


def split_by_silence(full, lines):
    """Cut one long recording into len(lines) clips at the pauses between the paragraphs.

    Writes each clip to line["mp3"]. Returns True only if the cut looks right: the right number of pauses
    was found and every clip's length roughly matches how long its text is. Otherwise returns False and
    writes nothing, so the caller can regenerate.
    """
    n = len(lines)
    total = probe(full)
    chars = [len(l["say"]) for l in lines]

    def judge(sel, lo, hi):
        cuts = [0.0] + [(a + b) / 2 for a, b in sel] + [total]
        # speech length of each line = from the end of the pause before it to the start of the pause after it
        speech = [(sel[k - 1][1] if k else 0.0, sel[k][0] if k < n - 1 else total) for k in range(n)]
        sp = [max(0.05, b - a) for a, b in speech]
        per_char = sum(sp) / max(1, sum(chars))
        ok = all(lo * per_char <= d / c <= hi * per_char and rate_ok(c, d)
                 for d, c in zip(sp, chars) if c >= 25)
        return ok, cuts

    for noise, dur in (("-38dB", 0.35), ("-38dB", 0.2), ("-32dB", 0.2), ("-35dB", 0.12)):
        r = subprocess.run(["ffmpeg", "-i", str(full), "-af", f"silencedetect=noise={noise}:d={dur}",
                            "-f", "null", "-"], capture_output=True, text=True)
        starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
        ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
        gaps = [(a, b) for a, b in zip(starts, ends) if a > 0.15 and b < total - 0.15]
        if len(gaps) < n - 1:
            continue
        tries = [(sorted(sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[: n - 1]), 0.4, 2.5)]
        if len(gaps) > n - 1:  # extra pauses inside lines: choose by position, not only by length
            near = _nearest_gaps(gaps, chars, total)
            if near:
                tries.append((near, 0.3, 3.3))
        for sel, lo, hi in tries:
            ok, cuts = judge(sel, lo, hi)
            if not ok:
                continue
            for k, l in enumerate(lines):
                tmp = l["mp3"].with_suffix(".part")
                run(["ffmpeg", "-y", "-i", str(full), "-ss", f"{cuts[k]:.3f}", "-to", f"{cuts[k + 1]:.3f}",
                     "-c:a", "pcm_s16le", "-f", "wav", str(tmp)])
                tmp.replace(l["mp3"])
            return True
    return False


SARVAM_MODEL = "bulbul:v3"
SARVAM_SPEAKER = "shubh"


def sarvam_tts_once(text, model, speaker, pace, out_wav, api_key):
    """One Sarvam Bulbul call -> WAV at out_wav. Raises on any failure."""
    body = {"text": text, "language_code": "hi-IN", "model": model, "speaker": speaker,
            "pace": pace, "speech_sample_rate": 24000, "output_audio_codec": "wav"}
    req = urllib.request.Request(
        "https://api.sarvam.ai/text-to-speech",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "api-subscription-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.load(r)
    audios = j.get("audios") or []
    if not audios:
        raise RuntimeError(f"Sarvam returned no audio: {json.dumps(j)[:300]}")
    tmp = out_wav.with_suffix(".part")
    tmp.write_bytes(base64.b64decode("".join(audios)))
    tmp.replace(out_wav)


async def tts_all(steps, meta, work, fake, provider):
    sem = asyncio.Semaphore(4)
    voice = meta.get("voice", "hi-IN-MadhurNeural")
    rate = meta.get("rate", "+0%")
    pitch = meta.get("pitch", "+0Hz")  # Edge only, e.g. "+2Hz" or "-3Hz"
    # Edge adds a long pause at every "।" and a medium one at every ",". For the options line (tight=True)
    # that is what makes "ऑप्शन ए ... [gap] ऑप्शन बी ..." feel slow. meta "option_gap": "none" | "short" | "normal"
    gap_mode = meta.get("option_gap", "short")

    def edge_text(s):
        t = s["say"]
        if s.get("tight") and gap_mode != "normal":
            if gap_mode == "none":
                t = re.sub(r"[।,]", " ", t)
            else:  # short: keep a comma between options (small pause), drop the long "।" pause
                t = t.replace("।", ",")
                t = re.sub(r"(ऑप्शन\s+\S+),", r"\1", t)  # no pause between "ऑप्शन ए" and its text
                t = t.rstrip(", ")
        return re.sub(r"\s+", " ", t).strip()

    g_voice = meta.get("gemini_voice", GEMINI_VOICE)
    g_models = meta.get("gemini_models") or ([meta["gemini_model"]] if meta.get("gemini_model") else GEMINI_MODELS)
    if isinstance(g_models, str):
        g_models = [g_models]
    g_style = meta.get("gemini_style", GEMINI_STYLE)
    g_delay = float(meta.get("gemini_delay", 21))  # free tier: 3 calls per minute per model
    g_batch = max(1, int(meta.get("gemini_batch", 1)))  # questions per Gemini call
    g_dead = set()  # models that hit their daily limit (or do not exist) in this run
    g_key = os.environ.get("GEMINI_API_KEY", "")
    if provider == "gemini" and not fake and not g_key:
        sys.exit("GEMINI_API_KEY is not set. Add it as a repository secret and pass it in video.yml (env).")
    g_lock = asyncio.Lock()
    s_model = meta.get("sarvam_model", SARVAM_MODEL)
    s_speaker = meta.get("sarvam_speaker", SARVAM_SPEAKER)
    s_pace = float(meta.get("sarvam_pace", 1.2))
    s_delay = float(meta.get("sarvam_delay", 1))
    s_key = os.environ.get("SARVAM_API_KEY", "")
    if provider == "sarvam" and not fake and not s_key:
        sys.exit("SARVAM_API_KEY is not set. Add it as a repository secret and pass it in video.yml (env).")
    s_sem = asyncio.Semaphore(2)

    async def sarvam_one(s, path):
        async with s_sem:
            last = None
            for attempt in range(5):
                try:
                    await asyncio.to_thread(sarvam_tts_once, s["say"], s_model, s_speaker, s_pace, path, s_key)
                    await asyncio.sleep(s_delay)
                    return
                except urllib.error.HTTPError as e:
                    body = e.read()[:300]
                    last = f"HTTP {e.code}: {body!r}"
                    if e.code in (400, 401, 403, 404, 422):  # bad key / speaker / model / text: retrying is pointless
                        break
                    wait = 10 * (attempt + 1)  # 429 or 5xx
                except Exception as e:
                    last = e
                    wait = 3 * (attempt + 1)
                print(f"  Sarvam retry {attempt + 1}/5 in {wait}s ({last})", flush=True)
                await asyncio.sleep(wait)
            sys.exit(f"Sarvam voice failed for: {s['say'][:60]}\n{last}\n"
                     "Check the key, credits, and that sarvam_speaker matches sarvam_model (lowercase). "
                     "Finished lines are cached: re-run to continue.")

    def g_path(s):
        # same cache file whichever model made it, so switching models mid-video keeps finished lines
        key = hashlib.md5(f"gemini|{g_voice}|{g_style}|{s['say']}".encode()).hexdigest()
        return work / "audio" / f"{key}.wav"

    def g_prompt(lines):
        text = "\n\n".join(l["say"] for l in lines)  # one paragraph per line: Gemini pauses between paragraphs
        return f"{g_style}: {text}" if g_style else text

    async def gemini_call(prompt, out):
        """One TTS call. Tries the models in order; a per-day 429 moves on to the next model."""
        while True:
            live = [m for m in g_models if m not in g_dead]
            if not live:
                print("Every Gemini model has hit its daily limit (or was not found). Finished lines are cached. "
                      "Re-run after the quota resets (about 1:30 pm IST), or add more models in meta gemini_models.",
                      flush=True)
                sys.exit(QUOTA_EXIT)
            model = live[0]
            minute_hits = fails = 0
            while True:
                try:
                    await asyncio.to_thread(gemini_tts_once, prompt, g_voice, model, out, g_key)
                    await asyncio.sleep(g_delay)
                    return
                except urllib.error.HTTPError as e:
                    code, body = e.code, e.read().decode("utf-8", "ignore")
                except Exception as e:  # network trouble, or the reply had no audio
                    code, body = 0, str(e)
                if code == 429:
                    if re.search(r"per\s*day", body, re.I) or minute_hits >= 4:
                        print(f"  {model}: daily limit reached, switching to the next model", flush=True)
                        g_dead.add(model)
                        break
                    minute_hits += 1
                    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', body)
                    wait = float(m.group(1)) + 2 if m else 25
                    print(f"  {model}: per-minute limit, waiting {wait:.0f}s", flush=True)
                    await asyncio.sleep(wait)
                    continue
                if code == 404:
                    print(f"  {model}: model not found, skipping it (check the name in AI Studio)", flush=True)
                    g_dead.add(model)
                    break
                if code in (400, 401, 403):
                    sys.exit(f"Gemini rejected the request (HTTP {code}) for {model}: {body[:300]}")
                fails += 1
                if fails > 5:
                    print(f"  {model}: keeps failing ({body[:120]}), switching to the next model", flush=True)
                    g_dead.add(model)
                    break
                print(f"  Gemini retry {fails}/5 in {5 * fails}s ({body[:120]})", flush=True)
                await asyncio.sleep(5 * fails)

    async def gemini_line(l):
        """One line, one call. If the clip is far too short or too long for its text, try once more."""
        for attempt in range(2):
            await gemini_call(g_prompt([l]), l["mp3"])
            if len(l["say"]) < 25 or rate_ok(len(l["say"]), probe(l["mp3"])):
                return
            print(f"  Clip length looks wrong for: {l['say'][:40]}...", flush=True)
            if attempt == 0:
                print("  generating that line again", flush=True)

    async def gemini_group(lines, deferred):
        """Make the audio for several lines with as few calls as possible (normally one).
        A group that cannot be cut cleanly is NOT redone line by line now (that costs many calls and used to eat the
        daily limit): it is put aside and done at the very end, after every normal group has its audio."""
        if len(lines) == 1:
            await gemini_line(lines[0])
            return
        full = work / "audio" / f"_group_{lines[0]['mp3'].stem}.wav"
        for attempt in range(2):
            await gemini_call(g_prompt(lines), full)
            if split_by_silence(full, lines):
                full.unlink(missing_ok=True)
                return
            if attempt == 0:
                print("  Could not cut the audio cleanly into lines, generating again", flush=True)
        full.unlink(missing_ok=True)
        print("  Still no clean cut: this group is set aside, to be made line by line at the end", flush=True)
        deferred.append(lines)

    async def gemini_all():
        nonlocal g_batch
        groups, order, seen = {}, [], set()
        # Free tier is about 10 calls a day per model. If the video needs more calls than the models can give in
        # one day, voice more questions per call (up to 3) instead of stopping half way. meta gemini_auto_batch false = off.
        nq = max([s["state"]["i"] for s in steps if "say" in s and s.get("state", {}).get("mode") not in ("intro", "outro")
                  and not s.get("filler") and "i" in s.get("state", {})] or [0])
        day_calls = max(1, int(meta.get("gemini_calls_per_day", 10))) * len(g_models)
        if meta.get("gemini_auto_batch", True) and nq and -(-nq // g_batch) + 3 > day_calls and g_batch < 3:
            g_batch = min(3, -(-nq // max(1, day_calls - 3)))
            print(f"Gemini: {nq} questions would need more calls than one day allows, so {g_batch} questions are "
                  f"voiced per call (meta gemini_auto_batch false turns this off)", flush=True)
        for s in steps:
            if "say" not in s:
                continue
            s["mp3"] = g_path(s)
            if s.get("filler"):
                if s["mp3"] in seen:
                    continue  # same filler line used twice in one video: voice it once
                seen.add(s["mp3"])
                gk = ("filler", (len(seen) - 1) // 4)  # four filler lines per call
            else:
                mode = s["state"]["mode"]
                gk = mode if mode in ("intro", "outro") else (s["state"]["i"] - 1) // g_batch
            if gk not in groups:
                groups[gk] = []
                order.append(gk)
            groups[gk].append(s)
        todo = [[s for s in groups[gk] if not (s["mp3"].exists() and s["mp3"].stat().st_size > 0)] for gk in order]
        todo = [t for t in todo if t]
        print(f"Gemini: {len(todo)} call group(s) to make, models: {', '.join(g_models)}", flush=True)
        deferred = []
        for n, lines in enumerate(todo, 1):
            print(f"  group {n}/{len(todo)} ({len(lines)} lines)", flush=True)
            await gemini_group(lines, deferred)
        if deferred:
            left = [l for lines in deferred for l in lines]
            print(f"Gemini: {len(deferred)} group(s) need {len(left)} single calls (all normal groups are done and cached)",
                  flush=True)
            for l in left:
                if not (l["mp3"].exists() and l["mp3"].stat().st_size > 0):
                    await gemini_line(l)

    async def one(s):
        if "say" not in s:
            return
        if provider == "gemini":
            mp3 = g_path(s)
        elif provider == "sarvam":
            key = hashlib.md5(f"sarvam|{s_model}|{s_speaker}|{s_pace}|{s['say']}".encode()).hexdigest()
            mp3 = work / "audio" / f"{key}.wav"
        else:
            key = hashlib.md5(f"{voice}|{rate}|{pitch}|{edge_text(s)}".encode()).hexdigest()
            mp3 = work / "audio" / f"{key}.mp3"
        s["mp3"] = mp3
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        if provider == "gemini" and not fake:
            return  # made by gemini_all()
        if provider == "sarvam" and not fake:
            await sarvam_one(s, mp3)
            return
        if fake:
            dur = max(1.5, len(s["say"]) * 0.075)
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=24000",
                 "-af", "volume=0.05", "-t", f"{dur:.2f}", "-acodec", "libmp3lame", str(mp3)])
            return
        import edge_tts
        last = None
        for attempt in range(4):
            try:
                async with sem:
                    await edge_tts.Communicate(edge_text(s), voice, rate=rate, pitch=pitch).save(str(mp3))
                if mp3.exists() and mp3.stat().st_size > 0:
                    return
            except Exception as e:  # network hiccup, retry
                last = e
                await asyncio.sleep(2 * (attempt + 1))
        sys.exit(f"Voice generation failed for: {s['say'][:60]}\n{last}")

    if provider == "sarvam":
        todo = {}
        for s in steps:
            if "say" in s:
                key = hashlib.md5(f"sarvam|{s_model}|{s_speaker}|{s_pace}|{s['say']}".encode()).hexdigest()
                if not (work / "audio" / f"{key}.wav").exists():
                    todo[s["say"]] = len(s["say"])
        chars = sum(todo.values())
        price = float(meta.get("sarvam_price_per_1000", 2))
        cost = chars / 1000 * price
        print(f"Sarvam: {chars} new characters to speak = about Rs {cost:.1f} at Rs {price:g} per 1,000 "
              "(lines already in the cache are free)", flush=True)
        cap = float(meta.get("sarvam_max_credits", 0))
        if cap and cost > cap and not fake:
            sys.exit(f"Stopped before spending anything: about Rs {cost:.1f} is over your sarvam_max_credits {cap:g}. "
                     "Raise it, or use lean_speech / max_points / fewer questions.")
    if provider == "gemini" and not fake:
        await gemini_all()
    # a filler line used twice in one video is voiced once (and paid for once)
    first, dup, todo_steps = {}, [], []
    for s in steps:
        if s.get("filler"):
            if s["say"] in first:
                dup.append((s, first[s["say"]]))
                continue
            first[s["say"]] = s
        todo_steps.append(s)
    await asyncio.gather(*(one(s) for s in todo_steps))
    for s, src in dup:
        s["mp3"] = src["mp3"]


def render_images(meta, qs, steps, work, theme, layout, fmt):
    from playwright.sync_api import sync_playwright
    cache = {}
    with sync_playwright() as p:
        try:  # the GitHub runner already has Google Chrome: no big browser download needed
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()  # Playwright's own Chromium
        page = browser.new_page(viewport={"width": W, "height": H})
        for n, s in enumerate(steps):
            key = json.dumps(s["state"], sort_keys=True)
            if key not in cache:
                img = work / "img" / f"{len(cache):04d}.png"
                page.set_content(page_html(meta, qs, s["state"], theme, layout, fmt))
                page.evaluate("document.fonts.ready")
                page.screenshot(path=str(img))
                cache[key] = img
            s["img"] = cache[key]
        browser.close()


def fmt_time(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


# names used by older versions of the PDF tool's Video JSON export -> real names
LEGACY = {"dark": "night", "light": "classic", "maroon": "royal",
          "standard": "quiz", "short": "revision", "landscape": "list", "portrait": "list"}


def pick(cli, meta_val, default, allowed):
    v = cli if cli and cli != "auto" else (meta_val or default)
    v = str(v).strip().lower()
    v = LEGACY.get(v, v) if v not in allowed else v
    if v not in allowed:
        sys.exit(f"Invalid value '{v}'. Allowed: {', '.join(allowed)}")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--out", default="output")
    ap.add_argument("--limit", type=int, default=0, help="only first N questions (0 = all)")
    ap.add_argument("--theme", default=None)
    ap.add_argument("--layout", default=None)
    ap.add_argument("--format", default=None)
    ap.add_argument("--tts", default=None, help="edge | gemini | sarvam (default: meta 'tts', else edge)")
    ap.add_argument("--fake-tts", action="store_true", help="silent placeholder audio, for layout tests")
    a = ap.parse_args()

    data = json.loads(Path(a.json_file).read_text(encoding="utf-8"))
    meta = data["meta"]
    theme = pick(a.theme, meta.get("theme"), "classic", list(THEMES))
    layout = pick(a.layout, meta.get("layout"), "list", ["list", "grid"])
    fmt = pick(a.format, meta.get("format"), "quiz", ["quiz", "revision"])
    provider = pick(a.tts, meta.get("tts"), "edge", ["edge", "gemini", "sarvam"])
    qs, steps = make_steps(data, a.limit, fmt)

    for i, q in enumerate(qs, 1):
        if len(q["points"]) > 4:
            print(f"WARNING Q{i}: more than 4 points, slide may overflow")
        for p in q["points"]:
            if len(norm_point(p)["show"]) > 110:
                print(f"WARNING Q{i}: a point is over 110 characters, shorten it: {norm_point(p)['show'][:40]}...")
        if q.get("trick") and len(norm_point(q["trick"])["show"]) > 120:
            print(f"WARNING Q{i}: trick is over 120 characters, shorten it")
        if len(q["q"]) > 170:
            print(f"WARNING Q{i}: question is very long, slide may overflow")

    n_fill = sum(1 for s in steps if s.get("filler"))
    if meta.get("filler_lines"):
        print(f"Fillers: {n_fill} filler line(s) placed between questions "
              f"(every {meta.get('filler_every', [3, 4])}), from {len(meta['filler_lines'])} lines")
        for ln in meta["filler_lines"]:
            if len(str(ln)) > 120:
                print(f"WARNING: filler line is over 120 characters, shorten it: {str(ln)[:40]}...")

    out = Path(a.out)
    work = out / "work"
    for d in ("audio", "img", "wav"):
        (work / d).mkdir(parents=True, exist_ok=True)

    print(f"{len(qs)} questions, {len(steps)} steps | theme={theme} layout={layout} format={fmt} tts={provider}")
    asyncio.run(tts_all(steps, meta, work, a.fake_tts, provider))
    # Gemini has no speed setting: speed it up here (pitch is preserved by atempo, valid range 0.5-2.0)
    speed = float(meta.get("gemini_speed", 1.3)) if provider == "gemini" and not a.fake_tts else 1.0
    tempo = f",atempo={speed:.3f}" if speed != 1.0 else ""
    # Gemini sometimes leaves long dead air inside a line: shorten any pause over 0.45 s (meta gemini_squeeze, 0 = off)
    sq = float(meta.get("gemini_squeeze", 0.2)) if provider == "gemini" and not a.fake_tts else 0
    squeeze = (f",silenceremove=stop_periods=-1:stop_duration=0.45:stop_threshold=-45dB:stop_silence={sq:.2f}"
               if sq > 0 else "")
    render_images(meta, qs, steps, work, theme, layout, fmt)

    # exact-length audio per step, then concat
    pause = float(meta.get("pause", PAUSE_DEFAULT))
    t = 0.0
    chapters = []
    img_lines, wav_lines = [], []
    for n, s in enumerate(steps):
        wav = work / "wav" / f"{n:04d}.wav"
        if "silence" in s:
            dur = s["silence"]
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                 "-t", f"{dur:.3f}", str(wav)])
        else:
            run(["ffmpeg", "-y", "-i", str(s["mp3"]), "-af", f"{TRIM}{squeeze}{tempo},apad=pad_dur={pause:.3f}",
                 "-ar", "48000", "-ac", "1", str(wav)])
            dur = probe(wav)
            if dur < 0.3:
                sys.exit(f"Voice clip came out empty for: {s['say'][:60]}")
        if "chapter" in s:
            chapters.append((t, s["chapter"]))
        img_lines += [f"file '{s['img'].resolve()}'", f"duration {dur:.3f}"]
        wav_lines.append(f"file '{wav.resolve()}'")
        t += dur
    img_lines.append(f"file '{steps[-1]['img'].resolve()}'")

    (work / "images.txt").write_text("\n".join(img_lines))
    (work / "audio.txt").write_text("\n".join(wav_lines))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "audio.txt"),
         "-c", "copy", str(work / "audio.wav")])
    mp4 = out / "video.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "images.txt"),
         "-i", str(work / "audio.wav"), "-vf", f"fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4)])

    title = (f'{meta["title"]} {meta.get("subtitle", "")} | {len(qs)} Questions with Answer & '
             f'Explanation | {meta.get("channel", "Target1st")}')
    desc = [title, "", "Chapters:"] + [f"{fmt_time(c)} {name}" for c, name in chapters]
    (out / "description.txt").write_text("\n".join(desc), encoding="utf-8")
    print(f"Done: {mp4}  ({fmt_time(t)} long)")


if __name__ == "__main__":
    main()
