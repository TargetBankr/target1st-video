#!/usr/bin/env python3
"""Target1st quiz video builder.

questions.json -> voice (Edge-TTS or Gemini AI voice) -> HTML slides (Playwright screenshots) -> one MP4 (FFmpeg).

Usage:
    python build.py questions.json --out output [--limit 2] [--theme night] [--layout grid]
                                    [--format revision] [--tts gemini] [--fake-tts]

theme:  classic | night | royal
layout: list | grid        (how the 4 options look on the question slide)
aspect: wide | reel        (wide = 1920x1080 YouTube; reel = 1080x1920 for Instagram, text kept inside Instagram's safe zone,
                            options always stacked, a slide that is too tall is shrunk by itself. Set meta "aspect": "reel"
                            or pass --aspect reel. Nothing else changes: same voice, same cache, same JSON.)
format: quiz | revision    (both read the options aloud; quiz adds a countdown, revision has none)
tts:    edge | gemini | sarvam   (edge = Edge-TTS, free, unlimited; gemini = Gemini AI voice, free tier is slow/limited;
                                  sarvam = Sarvam Bulbul Hindi voice, Rs 100 free credits then paid)
Each of these can also be set in the JSON "meta"; command-line values win ("auto" = use the JSON).
Old names from earlier versions of the PDF tool are converted automatically
(dark -> night, light -> classic, maroon -> royal, standard -> quiz, short -> revision,
landscape/portrait -> list).

HOW SPECIAL CHARACTERS ARE SPOKEN (the slide keeps the written text; only the voice changes)
    Built in: 32°43′N, 32°43 N, 28.6° E -> "32 डिग्री 43 मिनट उत्तर" (75°30′ प• = पश्चिम);
    °C, °F, %, ₹500, & are read in Hindi. प• / पं. / डॉ. / स्व. before a name = पंडित / डॉक्टर / स्वर्गीय,
    "प. बंगाल" = पश्चिम बंगाल, उ.प्र. = उत्तर प्रदेश, 326 ई.पू. = ईसा पूर्व. Your own list: meta "pronounce": {"RBI": "आर बी आई", "km": "किलोमीटर"}
    (Latin keys match whole words only).
    ANY line can be set by hand with "on screen || spoken" (question, options, points, trick) or, in points, with
    {"show": "...", "say": "..."}. The slide shows the first part, the voice reads the second EXACTLY as written
    (no automatic rewriting, no length limit on the spoken part). The 110 / 120 / 170 character warnings count the
    on-screen part only.

SPEECH PREP (Gemini, Sarvam and Edge voices, optional)
    meta "speech_prep": true  or your own message, e.g. "hi this is the video text which will be converted to speech
    so give texts for those number, symbol or line which may sound odd". A Gemini TEXT model rewrites the odd lines
    (numbers, symbols, codes, formulas) into spoken words before the voice is made; slides never change, "||" lines are
    never touched, answers are checked and cached (work/audio/_prep_cache.json), any failure falls back to the
    built-in rules. meta "speech_prep_models": ["gemini-2.5-flash", ...] to choose models (tried in order).
    With Sarvam or Edge voice the fixer still uses a GEMINI key (GEMINI_API_KEY; meta "speech_prep_key_slot": 2 for
    GEMINI_API_KEY_2) and the fixed wording is what Sarvam / Edge speak.

SEVERAL API KEYS (more videos from the daily limits / credits of each key)
    AUTO KEY SWITCH (Gemini voice, on by default): when every model of the current key has hit its daily limit, the build
    moves on by itself to the next key, in order key_slot, +1, +2 ... 5, then the lower slots (only keys whose secret
    exists in video.yml / GitHub). Lines already voiced stay cached. Exit code 75 only when ALL keys are used up.
    meta "key_auto_switch": false = stay on one key. Keys from the SAME Google project share one daily limit, so
    switching between them gains nothing: use keys from different projects.
    Set meta "key_slot": 2 to use the second key of the same engine: GEMINI_API_KEY_2 or SARVAM_API_KEY_2
    (slot 1 or nothing = GEMINI_API_KEY / SARVAM_API_KEY; slots 2 to 5 are wired in video.yml). Keys made in the
    SAME Google project share one Gemini daily limit; use keys from different projects for more quota.

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
    daily limit on EVERY key (see AUTO KEY SWITCH) the build stops cleanly with exit code 75 (video.yml sees this and resumes by itself after the
    quota resets, about 1:30 pm IST; every other failure exits with code 1).

GEMINI SAFETY (sync + empty clips), all automatic:
    - Gemini voices several lines in one call and build.py cuts the recording at the pauses. The cut now matches the
      pauses it finds to the pauses the TEXT predicts (every comma / danda / colon inside a line, and the gap between
      lines), so a pause inside the options line is no longer mistaken for the gap between two lines. A cut that still
      looks doubtful is NOT used: that group is split in half and voiced in smaller calls.
    - Spoken text for Gemini only (screen text and cache keys are unchanged): ".ppt" becomes " ppt" (the dot made Gemini
      return empty audio), and colons / semicolons / dashes inside a line are removed (they pause as long as a line gap).
      Symbols are spoken as words too (English words on an English line, Hindi words if the line has Hindi):
        <tr> -> "T R tag"   ___ -> "blank"   = + x / - -> equals plus times by minus   5:3 -> "5 to 3"   2-3 -> "2 to 3"
        F4 -> "F 4"   FF -> "F F"   Alt+F4 -> "Alt plus F 4"   11111111 (only on a line about binary) -> digit by digit
        km/h, m/s, "..." (becomes a comma), (brackets) (become commas), Blu-ray -> "Blu ray", EB PB OMR MICR HCF ... letters
        gemini_say_map     {"old": "new"}  extra words to respell for Gemini (applied first, wins over the built-ins)
        gemini_softpause   false = keep colons / dashes
        gemini_symbols     false = do not rewrite any symbols
      (spoken() also fixes "54 km/h" and "15 m/s" for every engine; before, km/h was read as "54 किलोमीटर /h".)
        gemini_cut_spread  default 2.1: how different the speaking speed of two lines in one cut may be
    - A clip that comes out empty or the wrong length is made again alone; if it is still bad, ONLY that line is voiced
      with Edge (meta "voice") and remembered (<hash>.edge.mp3). Delete that file to let Gemini try the line again.
    - Old saved clips that run far faster / slower than the rest of the video are re-made (meta gemini_audit false = off,
      gemini_audit_max = most clips re-made per run, default 6).
    - Picture changes sit on exact frame boundaries, and the end of the log prints SYNC CHECK (voice vs picture length)
      plus "CHECK AT m:ss" for any line spoken at a very different speed. meta sync_tolerance (default 0.25 s): the build
      stops instead of publishing a video whose voice and picture lengths differ by more.

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
import functools
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
# canvas per aspect: wide = YouTube 16:9, reel = Instagram / Shorts 9:16
ASPECTS = {"wide": (1920, 1080), "reel": (1080, 1920)}
# Reel safe zone (Instagram covers the top 220 px, the bottom 380 px and the right 120 px with its own buttons/caption)
REEL_TOP, REEL_BOTTOM, REEL_SIDE = 230, 380, 60
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

# 9:16 reel version of the same slides: 1080x1920, everything inside the Instagram safe zone
# (left 60, right 120, top 230, bottom 380). Options are always stacked cards (a 2x2 grid is too narrow here).
CSS_REEL = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1920px;background:var(--bg);font-family:var(--font);font-weight:700;color:var(--fg);position:relative;overflow:hidden}
.wm{position:absolute;left:0;right:0;top:780px;text-align:center;font-size:170px;color:var(--wm);transform:rotate(-24deg);z-index:0}
.wrap{position:absolute;left:60px;width:900px;top:230px;z-index:1}
.head{border-top:8px solid var(--rule);border-bottom:8px solid var(--rule);text-align:center;font-size:44px;line-height:1.25;padding:12px 0}
.q{color:var(--q);font-size:68px;line-height:1.32;margin-top:44px}
.opts{margin-top:36px}
.opt{font-size:56px;line-height:1.25;padding:16px 26px;margin-bottom:22px;border:5px solid var(--rule);border-radius:18px}
.cd{display:block;margin:30px auto 0;width:200px;height:200px;border:14px solid var(--cd);border-radius:50%;font-size:120px;color:var(--cd);text-align:center;line-height:172px;background:var(--bg)}
.badge{display:inline-block;margin-top:36px;background:var(--badgebg);color:var(--badgefg);font-size:40px;padding:6px 28px;border-radius:10px}
.ans{margin-top:26px;background:var(--ans);color:var(--ansfg);font-size:60px;line-height:1.25;padding:20px 28px;border-radius:14px;display:flex;align-items:center;gap:20px}
.ans svg{flex:none;width:64px;height:64px}
.pts{margin-top:32px}
.pt{font-size:54px;line-height:1.38;padding:12px 0;color:var(--pt)}
.pt b{color:var(--num);margin-right:12px}
.trick{margin-top:38px;background:var(--trickbg);color:var(--trickfg);border-radius:18px;padding:34px 38px;font-size:58px;line-height:1.4}
.trick .lbl{display:block;font-size:40px;margin-bottom:12px;opacity:.85}
.center{margin-top:380px;text-align:center;font-size:74px;line-height:1.5}
.center small{display:block;font-size:50px;color:var(--q);margin-top:30px}
.promo-t{font-size:68px;line-height:1.3;text-align:center;margin-top:70px}
.promo-t small{display:block;font-size:48px;color:var(--q);margin-top:18px}
.qrs{display:flex;gap:40px;justify-content:center;margin-top:80px}
.qrc{width:430px;background:#fff;color:#111;border-radius:28px;padding:22px 22px 26px;text-align:center;border:6px solid var(--rule)}
.qrc img{display:block;width:382px;height:382px}
.qrc .lab{font-size:42px;line-height:1.25;margin-top:14px}
"""

# Extra look for reels built with the retention effects (fx.py): word-by-word highlight, active option, countdown ring,
# question counter, hook card. Only added when page_html(..., fx=True); nothing here touches the plain slides.
CSS_REEL_FX = """
.kw.live .w{opacity:.42}
.kw.live .w.d{opacity:1}
.kw .w.on{opacity:1;background:var(--hl);color:var(--hlt,var(--bg));border-radius:10px;padding:0 8px;margin:0 -8px;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.opt.act{background:var(--q);border-color:var(--q);color:var(--bg)}
.ans{transform-origin:50% 50%}
.qn{display:inline-block;background:var(--badgebg);color:var(--badgefg);font-size:36px;line-height:1.2;padding:6px 26px;border-radius:999px;margin-bottom:16px}
.ringbox{position:relative;width:220px;height:220px;margin:26px auto 0}
.ringbox svg{position:absolute;left:0;top:0}
.ringbox span{position:absolute;left:0;top:0;width:220px;text-align:center;line-height:220px;font-size:108px;color:var(--cd)}
.hookc{margin-top:230px;text-align:center}
.hk-badge{display:inline-block;background:var(--badgebg);color:var(--badgefg);font-size:44px;line-height:1.2;padding:8px 36px;border-radius:999px}
.hk-t{font-size:112px;line-height:1.22;color:var(--q);margin-top:54px}
.hk-s{font-size:54px;line-height:1.3;margin-top:50px;color:var(--fg)}
"""
RING_R = 92

# checkpoint recap slide (every few questions in a long video): last answers on one page, wide look
CSS_CHECK = """
.rc{margin-top:22px}
.rr{font-size:50px;line-height:1.3;padding:5px 0;color:var(--pt)}
.rr b{display:inline-block;min-width:74px;color:var(--num)}
"""
# calm effects for YouTube (aspect wide): counter, ring bottom-right, small answer pop, trick highlight. No zoom.
CSS_LONG_FX = """
.qn{font-size:38px;line-height:1.2;padding:6px 26px;margin:26px 0 0 0}
.ringbox.lg{position:fixed;right:150px;bottom:40px;width:170px;height:170px;margin:0;z-index:2}
.ringbox.lg svg{width:170px;height:170px}
.ringbox.lg span{width:170px;line-height:170px;font-size:84px}
"""


def ring_html(show, num="", cls=""):
    """Countdown ring (SVG arc that fx.py shrinks frame by frame). show=False keeps its space but hides it."""
    c = 2 * 3.141592653589793 * RING_R
    vis = "" if show else ' style="visibility:hidden"'
    return (f'<div class="ringbox {cls}"{vis}><svg width="220" height="220" viewBox="0 0 220 220">'
            f'<circle cx="110" cy="110" r="{RING_R}" fill="none" style="stroke:var(--cd);opacity:.22" stroke-width="18"/>'
            f'<circle id="rc" cx="110" cy="110" r="{RING_R}" fill="none" style="stroke:var(--cd)" stroke-width="18" '
            f'stroke-linecap="round" stroke-dasharray="{c:.2f}" stroke-dashoffset="0" transform="rotate(-90 110 110)"/>'
            f'</svg><span id="rn">{num}</span></div>')


def kw(text, g):
    """Words of a text as <span class="w"> so fx.py can light them up one by one while they are spoken."""
    return " ".join(f'<span class="w" data-g="{g}" data-i="{i}">{html.escape(w, quote=False)}</span>'
                    for i, w in enumerate(str(text).split()))


# Promo slide (reels): two QR codes pop in one after the other and stay. POP[k-1] = size of the QR at animation frame k.
POP = [0.35, 0.75, 1.0, 1.14, 1.09, 1.04, 1.01, 1.0]
PROMO_ITEMS = [{"img": "assets/qr-notes.png", "label": "नोट्स + मॉक पेपर"},
               {"img": "assets/qr-mocks.png", "label": "ऑनलाइन मॉक टेस्ट"}]


def promo_items(meta):
    return (meta.get("promo_items") or PROMO_ITEMS)[:2]


@functools.lru_cache(maxsize=8)
def data_uri(path):
    f = Path(path)
    if not f.is_absolute():
        f = Path(__file__).resolve().parent / f
    return "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()


CHECK = ('<svg width="70" height="70" viewBox="0 0 24 24"><path d="M4 12.5l5 5L20 6.5" '
         'stroke="currentColor" stroke-width="3.2" fill="none" stroke-linecap="round" '
         'stroke-linejoin="round"/></svg>')


def esc(t):
    return html.escape(str(t), quote=False)


SAY0, SAY1 = "\x01", "\x02"   # wrap text the author set by hand ("show || say"): no automatic rewriting touches it


def split_pipes(t):
    """'on screen || spoken' -> (on screen, spoken). No '||' -> (text, None). The spoken part has NO length limit."""
    t = str(t)
    if "||" in t:
        a, b = t.split("||", 1)
        return a.strip(), (b.strip() or None)
    return t, None


def norm_point(p):
    """{"show", "say", "hand"}; hand = the spoken text was written by the author (|| or {"say": ...})."""
    if isinstance(p, dict):
        show, say = split_pipes(p["show"])
        if p.get("say"):
            say = p["say"]
        return {"show": show, "say": say or show, "hand": bool(say)}
    show, say = split_pipes(p)
    return {"show": show, "say": say or show, "hand": bool(say)}


def norm_question(q):
    """Question and options may also use 'show || spoken'. The slide gets the first part, the voice the second."""
    q = dict(q)
    q["q"], q["_qsay"] = split_pipes(q["q"])
    sp = [split_pipes(o) for o in q["options"]]
    q["options"] = [a for a, _ in sp]
    q["_osay"] = [b for _, b in sp]
    return q


def _hand(t):
    return SAY0 + t + SAY1


def page_html(meta, qs, st, theme, layout, fmt, aspect="wide", fx=False):
    reel = aspect == "reel"
    fxm = ("reel" if reel else "long") if fx else None   # long = YouTube effects: calm, no per-question zoom or highlight
    fx = fxm is not None
    if reel:
        layout = "list"
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
        if meta.get("intro_show"):   # a short hook on screen (reels): set by tools/make_reels.py
            small = meta.get("intro_small") or f"{len(qs)} प्रश्न · जवाब सोचिए!"
            if fx:
                body = (f'<div class="hookc"><div class="hk-badge">{esc(meta.get("channel", "Target1st"))}</div>'
                        f'<div class="hk-t">{esc(meta["intro_show"])}</div><div class="hk-s">{esc(small)}</div></div>')
            else:
                body = f'<div class="center">{esc(meta["intro_show"])}<small>{esc(small)}</small></div>'
        else:
            body = f'<div class="center">कुल {len(qs)} प्रश्न<small>{line}</small></div>'
    elif mode == "promo":
        items = promo_items(meta)

        def card(k, prog):
            if k >= len(items):
                return ""
            if prog <= 0:   # not shown yet: keeps its place so nothing jumps when it pops in
                return f'<div class="qrc" style="visibility:hidden"><img src="{data_uri(items[k]["img"])}"><div class="lab">.</div></div>'
            return (f'<div class="qrc" style="transform:scale({POP[min(prog, len(POP)) - 1]:.3f});opacity:{min(1.0, prog / 3):.2f}">'
                    f'<img src="{data_uri(items[k]["img"])}"><div class="lab">{esc(items[k]["label"])}</div></div>')
        body = (f'<div class="promo-t">{esc(meta.get("promo_title", "हरियाणा ग्रुप D के नोट्स और मॉक टेस्ट"))}'
                f'<small>{esc(meta.get("promo_sub", "लिंक बायो और हाइलाइट्स में"))}</small></div>'
                f'<div class="qrs">{card(0, st.get("a", 0))}{card(1, st.get("b", 0))}</div>')
    elif mode == "outro":
        body = (f'<div class="center">{esc(meta.get("outro_show", "देखने के लिए धन्यवाद!"))}'
                f'<small>{esc(meta.get("channel", "Target1st"))}</small></div>')
    elif mode == "hook":
        if st.get("stage", 0) == 0:
            body = (f'<div class="center" style="margin-top:170px"><span class="badge" style="margin:0 0 34px 0">'
                    f'{esc(meta.get("channel", "Target1st"))}</span>'
                    f'<div style="font-size:150px;line-height:1.2;color:var(--q)">{len(qs)} प्रश्न</div>'
                    f'<small>पेन तैयार रखिए · अपना स्कोर नोट कीजिए</small></div>')
        else:   # a preview of one question that really comes later in the video
            q = qs[st["i"] - 1]
            body = (f'<div class="badge">झलक · प्रश्न {st["i"]}</div>'
                    f'<div class="q" style="margin-top:34px">{st["i"]}. {esc(q["q"])}</div>')
    elif mode == "check":
        rows = ""
        for k in range(st["a"], st["i"] + 1):
            qq = qs[k - 1]
            ai = "ABCD".index(qq["answer"].strip().upper())
            rows += f'<div class="rr"><b>{k}</b>{"ABCD"[ai]}) {esc(qq["options"][ai])}</div>'
        body = (f'<div class="badge">चेकपॉइंट · {st["i"]} / {len(qs)}</div>'
                f'<div class="q" style="margin-top:26px">अपना स्कोर कमेंट में लिखिए</div>'
                f'<div class="rc">{rows}</div>')
    elif mode == "q":
        q = qs[st["i"] - 1]
        if fxm == "reel":
            body = (f'<div class="q kw" style="--hl:var(--q)"><div class="qn">प्रश्न {st["i"]} / {len(qs)}</div>'
                    f'<br>{st["i"]}. {kw(q["q"], "q")}</div>')
        elif fxm == "long":
            body = (f'<div class="qn">प्रश्न {st["i"]} / {len(qs)}</div>'
                    f'<div class="q" style="margin-top:14px">{st["i"]}. {esc(q["q"])}</div>')
        else:
            body = f'<div class="q">{st["i"]}. {esc(q["q"])}</div>'
        if st.get("opts"):
            cls = "opts grid" if layout == "grid" else "opts"
            body += f'<div class="{cls}">' + "".join(
                f'<div class="opt" data-o="{k}">{l}) {esc(t)}</div>' for k, (l, t) in enumerate(zip("ABCD", q["options"]))
            ) + "</div>"
        if fx and st.get("rb"):
            body += ring_html(st["rb"] == "show", st.get("cd", ""), "lg" if fxm == "long" else "")
        elif st.get("cd"):
            body += f'<div class="cd{" g" if layout == "grid" else ""}">{st["cd"]}</div>'
    elif mode == "answer":
        q = qs[st["i"] - 1]
        ans = q["answer"].strip().upper()
        idx = "ABCD".index(ans)
        body = (f'<div class="badge">प्रश्न {st["i"]}</div>'
                f'<div class="ans">{CHECK}<span>सही उत्तर: {ans}) {esc(q["options"][idx])}</span></div>'
                '<div class="pts">')
        for k, p in enumerate(q["points"][: st["pts"]], 1):
            txt = norm_point(p)["show"]
            if fxm == "reel" and k == st["pts"]:   # the point being spoken now lights up word by word
                body += f'<div class="pt kw" style="--hl:var(--num)"><b>{k}.</b>{kw(txt, f"p{k}")}</div>'
            else:
                body += f'<div class="pt"><b>{k}.</b>{esc(txt)}</div>'
        body += "</div>"
    elif mode == "trick":
        q = qs[st["i"] - 1]
        ttxt = norm_point(q["trick"])["show"]
        if fx:
            body = (f'<div class="badge">प्रश्न {st["i"]}</div>'
                    f'<div class="trick kw" style="--hl:var(--trickfg);--hlt:var(--trickbg)"><span class="lbl">ट्रिक</span>{kw(ttxt, "t")}</div>')
        else:
            body = (f'<div class="badge">प्रश्न {st["i"]}</div>'
                    f'<div class="trick"><span class="lbl">ट्रिक</span>{esc(ttxt)}</div>')
    if reel:
        # "fit" is shrunk (CSS zoom) by render_images only when a slide would run into the bottom safe zone
        return (f'<html><head><meta charset="utf-8"><style>{vars_css}{CSS_REEL}{CSS_REEL_FX if fx else ""}</style></head>'
                f'<body><div class="wm">Target1st</div><div class="wrap"><div id="fit">{head}{body}</div></div></body></html>')
    return (f'<html><head><meta charset="utf-8"><style>{vars_css}{CSS}{CSS_CHECK}{CSS_REEL_FX + CSS_LONG_FX if fx else ""}</style></head>'
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


DIR_WORD = {"N": "उत्तर", "S": "दक्षिण", "E": "पूर्व", "W": "पश्चिम",
            "उ": "उत्तर", "द": "दक्षिण", "पू": "पूर्व", "प": "पश्चिम"}
_DIRS = "N|S|E|W|पू|उ|द|प"
_END = r"(?![A-Za-z\u0900-\u097F])"
_DIR_MARK = r"[•०॰.]?"
_NUM = r"(\d+(?:\.\d+)?)"
# 32°43′12″ N   32° 43' N   32°43 N   28.6139° E   32°43′ उ•   (degrees, optional minutes, optional seconds, optional direction)
_COORD = re.compile(
    r"(?P<deg>\d+(?:\.\d+)?)\s*°\s*"
    r"(?:(?P<min>\d+(?:\.\d+)?)\s*(?:[′'’]|(?=\s*(?:" + _DIRS + r")" + _DIR_MARK + _END + r"))\s*)?"
    r"(?:(?P<sec>\d+(?:\.\d+)?)\s*(?:″|\"|''|”)\s*)?"
    r"(?:(?P<d>" + _DIRS + r")" + _DIR_MARK + _END + r")?")
_DV = r"\u0900-\u097F"
_MK = r"[•०॰.]"          # the dot / ring / bullet people type after a short form
_NB = r"(?<![" + _DV + r"A-Za-z])"   # not in the middle of a word
_TITLES = {"प": "पंडित", "पं": "पंडित", "डॉ": "डॉक्टर", "डा": "डॉक्टर", "स्व": "स्वर्गीय", "प्रो": "प्रोफेसर", "कु": "कुमारी"}
_STATES = {"उ": "उत्तर", "म": "मध्य", "हि": "हिमाचल", "आं": "आंध्र", "अ": "अरुणाचल"}
_LATIN = [  # (pattern, spoken); only used when the text is exactly this short form
    (r"sq\.?\s*km", "वर्ग किलोमीटर"), (r"km", "किलोमीटर"), (r"kg", "किलोग्राम"), (r"cm", "सेंटीमीटर"),
    (r"mm", "मिलीमीटर"), (r"ml", "मिलीलीटर"), (r"mg", "मिलीग्राम")]


def _coord_sub(m):
    deg, mins, secs, d = m.group("deg"), m.group("min"), m.group("sec"), m.group("d")
    out = f"{deg} डिग्री"
    if mins:
        out += f" {mins} मिनट"
    if secs:
        out += f" {secs} सेकंड"
    if d:
        out += " " + DIR_WORD[d]
    return out + " "


def spoken(text, pron):
    """What the voice should read for a line (the slide keeps its own text).
    1) meta "pronounce": {"RBI": "आर बी आई", ...}  your own list, longest key first, whole words for Latin keys.
    2) built in:
       coordinates   32°43′N, 32°43 N, 28.6° E, 75°30′ प•   -> 32 डिग्री 43 मिनट उत्तर ... पश्चिम
       titles        प• / पं. -> पंडित (but "प. बंगाल" -> पश्चिम बंगाल), डॉ. -> डॉक्टर, स्व. -> स्वर्गीय, प्रो., कु.; Dr, Prof, Pt, Mr, Mrs
       places/eras   उ.प्र. म.प्र. हि.प्र. आं.प्र. अ.प्र.; 326 ई.पू. -> ईसा पूर्व; 1857 ई. -> ईस्वी; वि.सं. -> विक्रम संवत
       units/symbols °C °F % ₹500 Rs. 500 & vs etc. i.e. e.g. No. 5, and 45 km / kg / cm / sq km after a number."""
    t = text
    for k in sorted(pron or {}, key=len, reverse=True):
        v = str(pron[k])
        if re.search(r"[A-Za-z0-9]", k[0]) or re.search(r"[A-Za-z0-9]", k[-1]):
            t = re.sub(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", lambda _m, v=v: v, t)
        else:
            t = t.replace(k, v)
    t = re.sub(r"°\s*C\b", " डिग्री सेल्सियस ", t)
    t = re.sub(r"°\s*F\b", " डिग्री फारेनहाइट ", t)
    t = _COORD.sub(_coord_sub, t)
    # eras and places first, so "ई.पू." / "उ.प्र." are not taken apart by the title rule
    t = re.sub(_NB + r"ई" + _MK + r"?\s*पू" + _MK + r"?(?![" + _DV + r"])", "ईसा पूर्व ", t)
    t = re.sub(r"(\d)\s*ई" + _MK + r"(?![" + _DV + r"])", r"\1 ईस्वी ", t)
    t = re.sub(_NB + r"वि" + _MK + r"?\s*सं" + _MK + r"?(?![" + _DV + r"])", "विक्रम संवत ", t)
    for ab, full in _STATES.items():
        t = re.sub(_NB + ab + _MK + r"\s*प्र" + _MK + r"?(?![" + _DV + r"])", full + " प्रदेश ", t)
    t = re.sub(_NB + r"पं?" + _MK + r"\s*(?=बंगाल)", "पश्चिम ", t)
    for ab, full in _TITLES.items():
        # "प०" needs a marker; the name must follow (a space and a letter), so "प" in a sentence is not touched
        t = re.sub(_NB + ab + _MK + r"(?=\s*[" + _DV + r"A-Za-z])", full + " ", t)
    for ab, full in (("Dr", "डॉक्टर"), ("Prof", "प्रोफेसर"), ("Pt", "पंडित"), ("Mr", "मिस्टर"), ("Mrs", "मिसेज़")):
        t = re.sub(r"(?<![A-Za-z])" + ab + r"\.?(?=\s+[A-Z])", full, t)
    t = re.sub(r"(?<![A-Za-z])vs\.?(?![A-Za-z])", "बनाम", t)
    t = re.sub(r"(?<![A-Za-z])etc\.?(?![A-Za-z])", "इत्यादि", t)
    t = re.sub(r"(?<![A-Za-z])i\.e\.?", "यानी", t)
    t = re.sub(r"(?<![A-Za-z])e\.g\.?", "जैसे", t)
    t = re.sub(r"(?<![A-Za-z])No\.?\s*(?=\d)", "नंबर ", t)
    t = re.sub(r"(?<![A-Za-z])Rs\.?\s*(\d(?:[\d,]*\d)?(?:\.\d+)?)", r"\1 रुपये", t)
    t = re.sub(r"₹\s*(\d(?:[\d,]*\d)?(?:\.\d+)?)", r"\1 रुपये", t)
    t = re.sub(r"(?<=\d)\s*km\s*/\s*h\b", " किलोमीटर प्रति घंटा ", t)   # "54 km/h" (was read as "54 किलोमीटर /h")
    t = re.sub(r"(?<=\d)\s*m\s*/\s*s\b", " मीटर प्रति सेकंड ", t)
    for pat, full in _LATIN:
        t = re.sub(r"(?<=\d)\s*" + pat + r"(?![A-Za-z])", " " + full + " ", t)
    t = t.replace("%", " प्रतिशत ").replace("&", " और ")
    return re.sub(r"[ \t]{2,}", " ", t).replace(" ,", ",").replace(" ।", "।").strip()


def _pt_say(p):
    n = norm_point(p)
    return _hand(n["say"]) if n["hand"] else n["say"]


CHECK_LINES = [
    "रुकिए! अब तक के प्रश्न गिनिए, कितने सही हुए? अपना स्कोर कमेंट में लिखिए।",
    "चेकपॉइंट! ऊपर के जवाब एक बार देख लीजिए, और अपना स्कोर कमेंट कीजिए।",
    "थोड़ा रुकिए, अपने सही उत्तर गिनिए और स्कोर कमेंट में बताइए।",
]
CHECK_CTA = "अगर वीडियो काम का लगे, तो Target1st चैनल को सब्सक्राइब कर लीजिए।"


def pick_preview(qs):
    """The question shown as a preview in the first seconds: one that really comes later in the video (never question 1),
    preferably one with a trick and a short text, around 60% of the way through. Returns a 1-based number or 0."""
    n = len(qs)
    if n < 4:
        return 0
    want = 0.6 * n
    cand = [i for i in range(3, n + 1) if qs[i - 1].get("trick") and len(qs[i - 1]["q"]) <= 140]
    if not cand:
        cand = [i for i in range(3, n + 1) if len(qs[i - 1]["q"]) <= 140] or list(range(3, n + 1))
    return min(cand, key=lambda i: abs(i - want))


def make_steps(data, limit, fmt, aspect="wide", long_fx=False):
    meta = data["meta"]
    qs = [norm_question(q) for q in (data["questions"][:limit] if limit else data["questions"])]
    fillers = plan_fillers(meta, len(qs))
    cd = int(meta.get("countdown", 5))
    lean = bool(meta.get("lean_speech", False))   # fewer spoken characters (cheaper voice): shorter option/answer lines
    max_pts = int(meta.get("max_points", 0))      # 0 = speak and show all points, 2 = only the first two
    intro = meta.get("intro") or ("नमस्कार दोस्तों! आज हम इस पेपर के प्रश्न हल करेंगे। "
                                  "हर प्रश्न के बाद सोचने का समय मिलेगा, फिर सही उत्तर और मुख्य पॉइंट्स बताए जाएंगे।"
                                  if fmt == "quiz" else
                                  "नमस्कार दोस्तों! आज हम इन प्रश्नों का तेज़ रिविज़न करेंगे। "
                                  "हर प्रश्न का सही उत्तर और उससे जुड़े मुख्य पॉइंट्स देखिए।")
    steps = []
    check_every = int(meta.get("checkpoint_every", 5)) if long_fx else 0
    check_secs = min(10.0, float(meta.get("checkpoint_secs", 9.0)))
    cta_at = 0       # the first checkpoint past 40% also asks for a subscribe, once
    if long_fx:
        pv = pick_preview(qs)
        hook_say = (f"नमस्कार दोस्तों! इस वीडियो में {len(qs)} प्रश्न हैं। पेन तैयार रखिए"
                    + (f", और पहले एक झलक देखिए। यह प्रश्न नंबर {pv} पर आएगा।" if pv else "।"))
        steps.append({"state": {"mode": "hook", "stage": 0}, "say": hook_say, "chapter": "Intro"})
        if pv:
            steps.append({"state": {"mode": "hook", "stage": 1, "i": pv},
                          "say": _hand(qs[pv - 1]["_qsay"]) if qs[pv - 1]["_qsay"] else qs[pv - 1]["q"]})
        if meta.get("intro"):   # an own intro text, spoken after the hook
            steps.append({"state": {"mode": "intro"}, "say": intro})
        if check_every:
            marks = [i for i in range(check_every, len(qs), check_every) if len(qs) - i >= 3]
            cta_at = next((i for i in marks if i >= 0.4 * len(qs)), 0)
    else:
        steps.append({"state": {"mode": "intro"}, "say": intro, "chapter": "Intro"})
    for i, q in enumerate(qs, 1):
        opts = q["options"]
        ans = q["answer"].strip().upper()
        idx = "ABCD".index(ans)
        # both formats: question, then options shown and read aloud. Only quiz adds the countdown.
        steps.append({"state": {"mode": "q", "i": i, "opts": False},
                      "say": _hand(q["_qsay"]) if q["_qsay"] else q["q"], "chapter": f"Q{i}"})
        osay = [_hand(h) if h else t for t, h in zip(opts, q["_osay"])]   # spoken form of each option
        say_opts = " ".join((f"{LET_SAY[l]}, {t}।" if lean else f"ऑप्शन {LET_SAY[l]}, {t}।")
                            for l, t in zip("ABCD", osay))
        steps.append({"state": {"mode": "q", "i": i, "opts": True}, "say": say_opts, "tight": True})
        if fmt == "quiz":
            for n in range(cd, 0, -1):
                steps.append({"state": {"mode": "q", "i": i, "opts": True, "cd": n}, "silence": 1.0})
        steps.append({"state": {"mode": "answer", "i": i, "pts": 0},
                      "say": (f"सही उत्तर {LET_SAY[ans]}, {osay[idx]}।" if lean
                              else f"सही उत्तर है, ऑप्शन {LET_SAY[ans]}, {osay[idx]}।")})
        for k, p in enumerate(q["points"][:max_pts] if max_pts else q["points"], 1):
            steps.append({"state": {"mode": "answer", "i": i, "pts": k}, "say": _pt_say(p)})
        if q.get("trick"):
            steps.append({"state": {"mode": "trick", "i": i}, "say": "ट्रिक। " + _pt_say(q["trick"])})
        if long_fx and check_every and i % check_every == 0 and i < len(qs) and len(qs) - i >= 3:
            say = CHECK_LINES[(i // check_every - 1) % len(CHECK_LINES)] + (" " + CHECK_CTA if i == cta_at else "")
            steps.append({"state": {"mode": "check", "i": i, "a": i - check_every + 1}, "say": say, "min_dur": check_secs})
            continue   # no filler line on top of a checkpoint
        if i in fillers:
            # spoken over the slide that is already on screen; the image is reused, so no new slide is rendered
            steps.append({"state": dict(steps[-1]["state"]), "say": fillers[i], "filler": True})
    if meta.get("promo"):
        if aspect != "reel":
            print("NOTE: meta promo is only for reels (aspect reel), skipped")
        else:
            n = len(POP)
            say1 = meta.get("promo_say1") or "ग्रुप डी की तैयारी के लिए पूरे नोट्स और मॉक टेस्ट चाहिए?"
            say2 = meta.get("promo_say2") or "दोनों के लिंक हमारे बायो और हाइलाइट्स में हैं। अभी देखिए।"
            hold = float(meta.get("promo_hold", 2.0))   # extra seconds the QR codes stay after the voice (5-7 s on screen in total)
            steps.append({"state": {"mode": "promo", "a": 0, "b": 0}, "say": say1, "chapter": "Notes and mocks"})
            for k in range(1, n + 1):
                steps.append({"state": {"mode": "promo", "a": k, "b": 0}, "silence": 1.0 / FPS})
            for k in range(1, n + 1):
                steps.append({"state": {"mode": "promo", "a": n, "b": k}, "silence": 1.0 / FPS})
            steps.append({"state": {"mode": "promo", "a": n, "b": n}, "say": say2})
            if hold > 0:
                steps.append({"state": {"mode": "promo", "a": n, "b": n}, "silence": hold})
    if meta.get("story"):
        pass   # Instagram story: hook, one question, QR promo - no outro (a story is 60 s at most)
    else:
        outro =meta.get("outro") or ("तो दोस्तों, आज के लिए बस इतना ही। वीडियो पसंद आया हो तो लाइक करें "
                                      "और Target1st चैनल को सब्सक्राइब ज़रूर करें।")
        steps.append({"state": {"mode": "outro"}, "say": outro, "chapter": "Outro"})
    pron = meta.get("pronounce") or {}
    for st in steps:
        if "say" in st:
            st["say_m"] = spoken(st["say"], pron)                      # still carries the hand-written markers
            st["say"] = st["say_m"].replace(SAY0, "").replace(SAY1, "")
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


async def edge_save(text, voice, rate, pitch, path):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))


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


# ---- Gemini voice safety helpers -------------------------------------------------------------------------------
# File types written with a leading dot (".ppt") are sometimes returned by Gemini as EMPTY audio. Spoken form: " ppt".
GEMINI_SAY_FILES = (r"(?<![\w.])\.(pptx?|docx?|xlsx?|pdf|txt|csv|exe|jpe?g|png|mp[34]|html?|sql|zip|ini|dll|bat)\b")
SPREAD_MAX = 2.1      # a cut is trusted only if no line is spoken more than this many times faster than another
EMPTY_SECONDS = 0.3   # a clip with less speech than this is "empty"


# Short forms Gemini may read as a word or swallow. Spoken letter by letter. Your own meta "gemini_say_map" wins over this.
GEMINI_SAY_DEFAULT = {"EB": "E B", "PB": "P B", "ULSI": "U L S I", "VLSI": "V L S I", "OMR": "O M R", "MICR": "M I C R",
                      "HCF": "H C F", "LCM": "L C M", "NIC": "N I C", "SUMIF": "SUM IF", "COUNTIF": "COUNT IF",
                      "MS-DOS": "M S DOS", "C-DAC": "C DAC"}
_DEV = re.compile(r"[ऀ-ॿ]")


def gemini_say(text, meta, marked=None):
    """Wrapper: text the author wrote after '||' (marked with SAY0/SAY1) is kept exactly; the rest gets the rules."""
    if not marked or SAY0 not in marked:
        return _say_rules(text, meta)
    hi = bool(_DEV.search(marked))
    out = []
    for i, seg in enumerate(re.split(f"[{SAY0}{SAY1}]", marked)):
        out.append(_say_rules(seg, meta, hi) if i % 2 == 0 else seg)   # odd parts are the hand-written ones
    t = re.sub(r"\s+", " ", " ".join(out)).strip()
    return re.sub(r"\s+([,।.?!])", r"\1", t)


def _say_rules(text, meta, hi=None):
    """The text Gemini actually speaks. The on-screen text and the cache key are NOT changed.
    Gemini returns EMPTY or wrong audio for things that are not words, so for the voice only:
      - HTML tags      <tr> -> "T R tag"          - blanks  ___ -> "blank"
      - maths          = + x / - and 5:3 -> "equals" "plus" "times" "by" "minus" "to"  (Hindi words if the line has Hindi)
      - keys / hex     F4 -> "F 4", FF -> "F F", Alt+F4 -> "Alt plus F 4"; 8-digit binary is read digit by digit
      - "km/h" "m/s", "..." (long pause), (brackets) (they become commas), hyphens inside words
      - short forms    EB PB OMR MICR HCF ... letter by letter (GEMINI_SAY_DEFAULT)
      - ".ppt" -> " ppt" (the dot made Gemini return empty audio)
      - colons, semicolons and dashes inside a line are removed (Gemini pauses at them as long as it pauses between
        two lines, which makes the lines impossible to cut apart). meta "gemini_softpause": false = keep them.
    meta "gemini_say_map": {"old": "new"} for any other word that fails; it is applied first and wins.
    meta "gemini_symbols": false = leave all symbols as they are."""
    t = text
    for old, new in (meta.get("gemini_say_map") or {}).items():
        t = t.replace(old, new)
    if meta.get("gemini_symbols", True):
        hi = bool(_DEV.search(t)) if hi is None else hi
        w = {"eq": "बराबर", "plus": "प्लस", "times": "गुणा", "by": "बटा", "minus": "घटा", "to": "से", "ratio": "अनुपात",
             "blank": "blank", "or": "या"} if hi else \
            {"eq": "equals", "plus": "plus", "times": "times", "by": "by", "minus": "minus", "to": "to",
             "ratio": "to", "blank": "blank", "or": "or"}
        for k, v in GEMINI_SAY_DEFAULT.items():
            if k not in (meta.get("gemini_say_map") or {}):
                t = re.sub(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", v, t)
        t = re.sub(r"</\s*(\w+)\s*>", lambda m: f" closing {_tag(m.group(1))} tag ", t)
        t = re.sub(r"<\s*(\w+)\s*/?>", lambda m: f" {_tag(m.group(1))} tag ", t)
        t = re.sub(r"_{2,}", f" {w['blank']} ", t)
        t = re.sub(r"\bkm\s*/\s*h\b", "kilometres per hour", t)
        t = re.sub(r"\bkmph\b", "kilometres per hour", t)
        t = re.sub(r"(?<=\d)\s*m\s*/\s*s\b", " metres per second", t)  # 15 m/s
        t = re.sub(r"\.{3}|…", ", ", t)
        if re.search(r"(?i)binary|\u092c\u093e\u0907\u0928\u0930\u0940|\bbits?\b|\bbytes?\b", t):  # 8 / 16 digit binary, digit by digit
            t = re.sub(r"(?<![\w.])([01]{4})([01]{4})(?:([01]{4})([01]{4}))?(?![\w.])",
                       lambda m: " ".join(" ".join(g) for g in m.groups() if g), t)
        t = re.sub(r"\b([A-Z])(\d{1,2})\b", r"\1 \2", t)                # F4 F12 V3 -> F 4
        t = re.sub(r"\b(?=[0-9A-F]*[A-F])(?=[0-9A-F]*[A-F0-9])([0-9A-F]{2})\b",
                   lambda m: " ".join(m.group(1)), t)                   # hex FF F0 1F EE CD
        t = re.sub(r"(?<=\d)\s*[xX×]\s*(?=\d)", f" {w['times']} ", t)
        t = re.sub(r"(?<=[\w)])\s+[xX\u00d7]\s+(?=[\w(])", f" {w['times']} ", t)   # MP x (100..) , a x b
        t = re.sub(r"(?<=[\w)])\s*/\s*(?=[\d(])|(?<=[\d)])\s*/\s*(?=[\w(])|(?<=[\w)])\s+/\s+(?=[\w(])",
                   f" {w['by']} ", t)                                   # 150 / 10 , 3/4 , ) / 100 , x / y
        t = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", f" {w['or']} ", t)     # has/have, hub/switch
        t = re.sub(r"(?<=\d)-(?=\d)", f" {w['to']} ", t)               # 2-3 years
        t = re.sub(r"\s-\s", f" {w['minus']} ", t)                      # 500 - 50
        t = re.sub(r"(?<=[A-Za-zऀ-ॿ])-(?=[A-Za-zऀ-ॿ])", " ", t)  # Blu-ray, black-white
        t = re.sub(r"(?<![\d:])(\d)\s*:\s*(\d)(?![\d:])", rf"\1 {w['ratio']} \2", t)  # ratio 5:3 (10:30 is a time)
        t = re.sub(r"\s*=\s*", f" {w['eq']} ", t)
        t = re.sub(r"\s*\+\s*", f" {w['plus']} ", t)
        t = re.sub(r"(\d)x\b", r"\1 x", t)                            # 3x -> 3 x
        t = re.sub(r"\s*\(\s*", ", ", t)                                # (brackets) -> commas
        t = re.sub(r"\s*\)\s*", ", ", t)
        t = re.sub(r"(,\s*){2,}", ", ", t)
        t = re.sub(r"\s+,", ",", t)
        t = re.sub(r",\s*([.?!।])", r"\1", t)
        t = re.sub(r"^\s*,\s*", "", t)
    t = re.sub(GEMINI_SAY_FILES, r" \1", t, flags=re.I)
    if meta.get("gemini_softpause", True):
        t = re.sub(r"(?<!\d)\s*[:;]\s*(?!\d)", " ", t)
        t = re.sub(r"\s*[—–]\s*", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tag(name):
    """HTML tag name as it is spoken: short ones letter by letter (tr -> T R), longer ones as the word."""
    n = name.lower()
    return " ".join(n.upper()) if len(n) <= 2 or n in ("html", "css") else n


# ---- Gemini TEXT model "speech prep" -------------------------------------------------------------------------------
# meta "speech_prep": true  or  your own message. A text model reads the video lines and writes the spoken form of
# the ones that would sound odd (numbers, symbols, codes, formulas). Slides never change. Lines you wrote by hand
# with "show || spoken" are never touched. Any failure falls back to the built-in rules.
SPEECH_PREP_MSG = ("hi this is the video text which will be converted to speech so give texts for those number, "
                   "symbol or line which may sound odd")
SPEECH_PREP_MODELS = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
_ODD = re.compile(r"[0-9=+×÷/<>_%@#&*^~|\\]|\b[A-Z]{2,}\b|\.[A-Za-z]{2,4}\b")
_PH = re.compile(r"\[\[(\d+)\]\]")


def gemini_text_once(prompt, model, api_key):
    """One Gemini text call that must answer in JSON. Returns the parsed object. Raises on any failure."""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.load(r)
    txt = "".join(pt.get("text", "") for c in j.get("candidates", []) for pt in c.get("content", {}).get("parts", []))
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)


def _prep_ok(src, out, holes):
    if not isinstance(out, str) or not out.strip():
        return False
    if len(out) > 3 * len(src) + 60 or re.search(r"[{}\[\]`*#]", _PH.sub("", out)):
        return False
    if _DEV.search(src) and not _DEV.search(out):
        return False
    return sorted(_PH.findall(out)) == sorted(str(i) for i in range(len(holes)))


def speech_prep(steps, meta, work, api_key, call=None):
    """Sets s["prep"] (spoken form, hand-written parts restored in SAY0/SAY1 markers) for odd lines."""
    msg = meta.get("speech_prep")
    if not msg:
        return
    msg = msg if isinstance(msg, str) and len(msg) > 8 else SPEECH_PREP_MSG
    models = meta.get("speech_prep_models") or SPEECH_PREP_MODELS
    call = call or gemini_text_once
    cache_f = work / "audio" / "_prep_cache.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    ck = lambda t: hashlib.md5((msg + "|" + t).encode()).hexdigest()
    jobs = []                     # (step, source text with [[n]] holes, hand parts)
    for s in steps:
        m = s.get("say_m")
        if not m or s.get("filler") or s.get("state", {}).get("mode") in ("intro", "outro"):
            continue
        holes = []
        def hole(mo):
            holes.append(mo.group(1))
            return f"[[{len(holes) - 1}]]"
        src = re.sub(f"{SAY0}(.*?){SAY1}", hole, m, flags=re.S)
        if _ODD.search(_PH.sub("", src)):
            jobs.append((s, src, holes))
    if not jobs:
        return
    todo = [j for j in jobs if ck(j[1]) not in cache]
    for a in range(0, len(todo), 30):
        chunk = todo[a:a + 30]
        prompt = (msg + "\n\nBelow is a JSON object: id -> one line of the video text (Hindi/English quiz, read by a "
                  "text-to-speech voice). Return a JSON object with the same ids. For each line give the text exactly "
                  "as it should be SPOKEN: write numbers, symbols, formulas, codes, tags, file names and short forms "
                  "out in words (in Hindi script on Hindi lines, English words on English lines), spell letter-codes "
                  "letter by letter, change nothing else, keep the wording, keep every [[n]] marker exactly as it is, "
                  "no explanations, no markdown. If a line already sounds fine, return it unchanged.\n\n"
                  + json.dumps({str(i): j[1] for i, j in enumerate(chunk)}, ensure_ascii=False))
        res, last = None, None
        for model in models:
            try:
                res = call(prompt, model, api_key)
                print(f"Speech prep: {len(chunk)} line(s) sent to {model}", flush=True)
                break
            except Exception as e:
                last = e
                print(f"Speech prep: {model} failed ({str(e)[:120]})", flush=True)
        if not isinstance(res, dict):
            print(f"Speech prep: no model answered, built-in rules are used for {len(chunk)} line(s) ({last})", flush=True)
            continue
        for i, (_, src, holes) in enumerate(chunk):
            out = res.get(str(i))
            if _prep_ok(src, out, holes):
                cache[ck(src)] = out.strip()
            else:
                print(f"Speech prep: answer for a line was rejected, rule-based text is used: {src[:50]}", flush=True)
    try:
        cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    shown = 0
    for s, src, holes in jobs:
        out = cache.get(ck(src))
        if not out:
            continue
        s["prep"] = _PH.sub(lambda mo: _hand(holes[int(mo.group(1))]), out)
        if out != src and shown < 40:
            print(f"    prep: {src[:60]}  ->  {out[:80]}", flush=True)
            shown += 1


def line_weight(text):
    """Expected speaking time of a line, in 'characters': every comma / danda inside the line adds a pause."""
    body = text.rstrip(" ,।.?!;:")
    return len(text) + 4 * len(re.findall(r"[,।;:?!]", body))


def speech_seconds(path):
    """Length of the clip with the silence at both ends removed (the same trim the final build applies)."""
    tmp = Path(str(path) + ".trimcheck.wav")
    try:
        run(["ffmpeg", "-y", "-i", str(path), "-af", TRIM, "-ar", "24000", "-ac", "1", str(tmp)])
        return probe(tmp)
    except (SystemExit, ValueError):  # an all-silent clip trims to nothing: no length at all
        return 0.0
    finally:
        tmp.unlink(missing_ok=True)


def _nearest_gaps(gaps, weights, total):
    """Pick len(weights)-1 pauses, in order, that sit closest to where each line should end if every 'character' took
    the same time, with a bonus for longer pauses (the gap between paragraphs is longer than a comma pause)."""
    n = len(weights)
    tot = sum(weights) or 1
    exp = [total * sum(weights[:k]) / tot for k in range(1, n)]
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


def _events(texts, wts):
    """The pauses Gemini is expected to make, in order: one at every comma / danda / colon inside a line (optional,
    Gemini may skip it) and one between every two lines (must exist). Each has its expected position in 'characters'."""
    ev, base = [], 0
    for k, t in enumerate(texts):
        end = len(t.rstrip(" ,\u0964.?!;:"))
        marks = 0
        for i, ch in enumerate(t[:end]):
            if ch in ",\u0964;:?!":
                ev.append((base + i + 4 * marks, False))
                marks += 1
        base += wts[k]
        if k < len(texts) - 1:
            ev.append((base, True))
    return ev, base


def _align_gaps(gaps, texts, wts, total):
    """Match the pauses found in the recording to the pauses the text predicts (monotone alignment, Viterbi).
    A pause inside a line may be unmatched (Gemini skipped it); a pause between two lines may not.
    Returns (boundary gaps, cost per event, worst boundary position error in seconds) or None."""
    ev, W = _events(texts, wts)
    M, G = len(ev), len(gaps)
    nb = [0]
    for e in ev:
        nb.append(nb[-1] + (1 if e[1] else 0))
    if G < nb[-1] or not nb[-1]:
        return None
    r = total / max(1, W)
    tau = [r * e[0] for e in ev]
    mids = [(a + b) / 2 for a, b in gaps]
    lens = [b - a for a, b in gaps]
    C_SKIP, C_EXTRA = 1.0, 0.15

    def here(i, j):
        sc = 0.5 + 0.08 * tau[i]
        return ((mids[j] - tau[i]) / sc) ** 2 - (2.0 if ev[i][1] else 1.0) * lens[j]

    best = {}
    for i in range(M):
        if nb[i] > 0:
            break
        for j in range(G):
            best[(i, j)] = (C_SKIP * i + C_EXTRA * j + here(i, j), None)
    for i in range(M):
        for j in range(G):
            cur = best.get((i, j))
            if cur is None:
                continue
            for i2 in range(i + 1, M):
                if nb[i2] - nb[i + 1] > 0:
                    break
                for j2 in range(j + 1, G):
                    c = cur[0] + C_SKIP * (i2 - i - 1) + C_EXTRA * (j2 - j - 1) + here(i2, j2)
                    old = best.get((i2, j2))
                    if old is None or c < old[0]:
                        best[(i2, j2)] = (c, (i, j))
    end, end_cost = None, float("inf")
    for (i, j), (c, _) in best.items():
        if nb[M] - nb[i + 1] > 0:
            continue
        c += C_SKIP * (M - 1 - i) + C_EXTRA * (G - 1 - j)
        if c < end_cost:
            end, end_cost = (i, j), c
    if end is None:
        return None
    chain, node = [], end
    while node is not None:
        chain.append(node)
        node = best[node][1]
    chain.reverse()
    bounds = [(i, j) for i, j in chain if ev[i][1]]
    if len(bounds) != nb[-1]:
        return None
    err = max(abs(mids[j] - tau[i]) for i, j in bounds)
    return [gaps[j] for _, j in bounds], end_cost / max(1, M), err


def split_by_silence(full, lines, spread_max=SPREAD_MAX):
    """Cut one long recording into len(lines) clips at the pauses between the lines.

    Every way of choosing the pauses is tried (several silence thresholds, longest pauses, best position fit) and the
    cut where all lines are spoken at the most similar speed wins. It is used only if that spread is <= spread_max.
    Writes each clip to line["mp3"] and returns True; otherwise returns False and writes nothing, so the caller
    can regenerate or split the group into smaller calls (fewer lines per call = far less ambiguity).
    """
    n = len(lines)
    total = probe(full)
    texts = [l.get("vsay") or l["say"] for l in lines]
    chars = [len(t) for t in texts]
    wts = [max(1, line_weight(t)) for t in texts]
    best = None  # (alignment cost, spread, cuts)

    def judge(sel):
        speech = [(sel[k - 1][1] if k else 0.0, sel[k][0] if k < n - 1 else total) for k in range(n)]
        sp = [b - a for a, b in speech]
        if any(d < 0.25 for d in sp):
            return None
        if not all(rate_ok(c, d) for d, c in zip(sp, chars) if c >= 25):
            return None
        rates = [w / d for w, d in zip(wts, sp) if w >= 12]
        spread = max(rates) / min(rates) if len(rates) > 1 else 1.0
        return spread, [0.0] + [(a + b) / 2 for a, b in sel] + [total]

    for noise, dur in (("-38dB", 0.35), ("-38dB", 0.2), ("-32dB", 0.2), ("-35dB", 0.12), ("-35dB", 0.08)):
        r = subprocess.run(["ffmpeg", "-i", str(full), "-af", f"silencedetect=noise={noise}:d={dur}",
                            "-f", "null", "-"], capture_output=True, text=True)
        starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
        ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
        gaps = [(a, b) for a, b in zip(starts, ends) if a > 0.15 and b < total - 0.15]
        if len(gaps) < n - 1:
            continue
        al = _align_gaps(gaps, texts, wts, total)
        if al is None:
            continue
        sel, cost, err = al
        j = judge(sel)
        if j and err <= max(1.0, 0.12 * total) and (best is None or cost < best[0]):
            best = (cost, j[0], j[1])
    if best is not None:
        best = (best[1], best[2])
    if best is None or best[0] > spread_max:
        print(f"    cut not trusted (best speed spread {best[0]:.2f} > {spread_max})" if best
              else "    cut not trusted (no usable pauses found)", flush=True)
        return False
    cuts = best[1]
    for k, l in enumerate(lines):
        tmp = l["mp3"].with_suffix(".part")
        run(["ffmpeg", "-y", "-i", str(full), "-ss", f"{cuts[k]:.3f}", "-to", f"{cuts[k + 1]:.3f}",
             "-c:a", "pcm_s16le", "-f", "wav", str(tmp)])
        tmp.replace(l["mp3"])
    print(f"    cut ok: {n} lines, speed spread {best[0]:.2f}, cuts at "
          + " ".join(f"{c:.1f}" for c in cuts[1:-1]), flush=True)
    return True


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
    # key_slot picks WHICH key of the same engine this video uses: 1 (or empty) = GEMINI_API_KEY / SARVAM_API_KEY,
    # 2 = GEMINI_API_KEY_2 / SARVAM_API_KEY_2, and so on. The voice engine and settings stay the same, so the voice
    # cache is shared between keys (lines already voiced are never paid for again).
    try:
        slot = int(meta.get("key_slot") or 1)
    except (TypeError, ValueError):
        slot = 0
    if not 1 <= slot <= 5:
        sys.exit(f"meta key_slot must be a number from 1 to 5, got {meta.get('key_slot')!r}")
    g_env = "GEMINI_API_KEY" + (f"_{slot}" if slot > 1 else "")
    s_env = "SARVAM_API_KEY" + (f"_{slot}" if slot > 1 else "")
    g_key = os.environ.get(g_env, "")
    if provider == "gemini" and not fake and not g_key:
        sys.exit(f"{g_env} is not set. Add it as a repository secret (name exactly {g_env}) and pass it in video.yml (env).")
    if provider in ("gemini", "sarvam") and not fake:
        print(f"Key: using {g_env if provider == 'gemini' else s_env} (key_slot {slot})", flush=True)
    g_lock = asyncio.Lock()
    # AUTO KEY SWITCH (Gemini voice): when every model of the current key is out of daily quota, the next key is used
    # (key_slot first, then upwards 2-3-4-5, then the lower slots). Only keys whose secret is set are used.
    # meta "key_auto_switch": false = never switch (stop with exit code 75 instead).
    k_order = [slot] + list(range(slot + 1, 6)) + list(range(1, slot))
    kst = {"slot": slot, "key": g_key, "tried": [slot]}
    k_auto = bool(meta.get("key_auto_switch", True)) and provider == "gemini" and not fake

    def switch_key(failed_slot):
        """Make the next unused key active. True if there is one (or another call already switched)."""
        if kst["slot"] != failed_slot:
            return True
        for n in k_order:
            if n in kst["tried"]:
                continue
            v = os.environ.get("GEMINI_API_KEY" + (f"_{n}" if n > 1 else ""), "")
            if v:
                kst["tried"].append(n)
                kst["slot"], kst["key"] = n, v
                g_dead.clear()
                print(f"  Key slot {failed_slot} is out of daily quota -> switching to key slot {n} "
                      f"(GEMINI_API_KEY{'_' + str(n) if n > 1 else ''})", flush=True)
                return True
        return False
    s_model = meta.get("sarvam_model", SARVAM_MODEL)
    s_speaker = meta.get("sarvam_speaker", SARVAM_SPEAKER)
    s_pace = float(meta.get("sarvam_pace", 1.2))
    s_delay = float(meta.get("sarvam_delay", 1))
    s_key = os.environ.get(s_env, "")
    if provider == "sarvam" and not fake and not s_key:
        sys.exit(f"{s_env} is not set. Add it as a repository secret (name exactly {s_env}) and pass it in video.yml (env).")
    s_sem = asyncio.Semaphore(2)

    if provider in ("sarvam", "edge") and meta.get("speech_prep") and not fake:
        # the AI fixer is a Gemini TEXT model, so it needs a Gemini key even when the voice is Sarvam / Edge
        ps = int(meta.get("speech_prep_key_slot", 1) or 1)
        pk = os.environ.get("GEMINI_API_KEY" + (f"_{ps}" if ps > 1 else ""), "")
        if not pk:
            print("Speech prep skipped: no GEMINI_API_KEY in this run (add the secret, or set meta speech_prep_key_slot)", flush=True)
        else:
            try:
                speech_prep(steps, meta, work, pk)
                for st in steps:
                    if st.get("prep"):
                        st["say"] = st["prep"].replace(SAY0, "").replace(SAY1, "")   # new wording -> new voice clip
            except Exception as e:
                print(f"Speech prep skipped: {e}", flush=True)

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
        key = hashlib.md5(f"gemini|{g_voice}|{g_style}|{s.get('prep_key') or s['say']}".encode()).hexdigest()
        return work / "audio" / f"{key}.wav"

    def g_edge_path(s):
        return g_path(s).with_suffix(".edge.mp3")  # Edge voice used for ONE line Gemini could not voice

    def g_prompt(lines):
        text = "\n\n".join(l.get("vsay") or l["say"] for l in lines)  # one paragraph per line: Gemini pauses between paragraphs
        return f"{g_style}: {text}" if g_style else text

    async def gemini_call(prompt, out):
        """One TTS call. Tries the models in order; a per-day 429 moves on to the next model."""
        while True:
            cur = kst["slot"]
            live = [m for m in g_models if m not in g_dead]
            if not live:
                if k_auto and switch_key(cur):
                    continue
                print("Every Gemini model has hit its daily limit (or was not found)"
                      + (f" on every key tried (slots {', '.join(map(str, kst['tried']))})" if len(kst["tried"]) > 1 else "")
                      + ". Finished lines are cached. Re-run after the quota resets (about 1:30 pm IST), "
                      "or add more models in meta gemini_models / more keys.", flush=True)
                sys.exit(QUOTA_EXIT)
            model = live[0]
            minute_hits = fails = 0
            while True:
                try:
                    await asyncio.to_thread(gemini_tts_once, prompt, g_voice, model, out, kst["key"])
                    await asyncio.sleep(g_delay)
                    return
                except urllib.error.HTTPError as e:
                    code, body = e.code, e.read().decode("utf-8", "ignore")
                except Exception as e:  # network trouble, or the reply had no audio
                    code, body = 0, str(e)
                if code == 429:
                    if re.search(r"per\s*day", body, re.I) or minute_hits >= 4:
                        print(f"  {model}: daily limit reached, switching to the next model", flush=True)
                        if kst["slot"] == cur:
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
                    if kst["slot"] == cur:
                        g_dead.add(model)
                    break
                if code in (400, 401, 403):
                    sys.exit(f"Gemini rejected the request (HTTP {code}) for {model}: {body[:300]}")
                fails += 1
                if fails > 5:
                    print(f"  {model}: keeps failing ({body[:120]}), switching to the next model", flush=True)
                    if kst["slot"] == cur:
                        g_dead.add(model)
                    break
                print(f"  Gemini retry {fails}/5 in {5 * fails}s ({body[:120]})", flush=True)
                await asyncio.sleep(5 * fails)

    def line_good(l):
        """False if the clip is missing, empty, or its length does not fit its text."""
        p = l["mp3"]
        if not p.exists() or p.stat().st_size == 0:
            return False
        d = speech_seconds(p)
        if d < EMPTY_SECONDS:
            return False
        t = l.get("vsay") or l["say"]
        return len(t) < 25 or rate_ok(len(t), d)

    async def edge_fallback(l):
        """Gemini could not voice this line (empty audio twice): voice this ONE line with Edge instead."""
        p = g_edge_path(l)
        print(f"  Gemini gave no usable audio for: {l['say'][:50]} -> Edge voice for this line only", flush=True)
        last = None
        for attempt in range(3):
            try:
                async with sem:
                    await edge_save(edge_text(l), voice, rate, pitch, p)
                if p.exists() and p.stat().st_size > 0 and speech_seconds(p) >= EMPTY_SECONDS:
                    l["mp3"], l["edge_fb"] = p, True
                    l["mp3"].with_suffix(".aud").touch()
                    return
            except Exception as e:
                last = e
            await asyncio.sleep(2 * (attempt + 1))
        sys.exit(f"Gemini AND Edge both failed for: {l['say'][:60]}\n{last}\n"
                 "Add the word to meta gemini_say_map (e.g. {\"abc\": \"a b c\"}) or reword the line.")

    async def gemini_line(l):
        """One line, one call. Empty / wrong length -> one more try, then Edge for this line only."""
        for attempt in range(2):
            await gemini_call(g_prompt([l]), l["mp3"])
            if line_good(l):
                l["mp3"].with_suffix(".aud").touch()
                return
            print(f"  Clip is empty or the wrong length for: {l['say'][:40]}..."
                  + (" (generating it again)" if attempt == 0 else ""), flush=True)
        await edge_fallback(l)

    async def gemini_group(lines):
        """Make the audio for several lines with as few calls as possible (normally one).
        If the recording cannot be cut into lines with confidence, the group is split in half and each half is
        voiced in its own call (2-4 lines per call are almost never ambiguous). Never guesses a cut."""
        if len(lines) == 1:
            await gemini_line(lines[0])
            return
        full = work / "audio" / f"_group_{lines[0]['mp3'].stem}.wav"
        await gemini_call(g_prompt(lines), full)
        ok = split_by_silence(full, lines, float(meta.get("gemini_cut_spread", SPREAD_MAX)))
        full.unlink(missing_ok=True)
        if ok:
            return
        mid = len(lines) // 2
        print(f"  Cannot cut these {len(lines)} lines safely: voicing {mid} + {len(lines) - mid} lines in separate calls",
              flush=True)
        await gemini_group(lines[:mid])
        await gemini_group(lines[mid:])

    def audit_cache(lines):
        """Old clips made by an earlier cut can hold a neighbour's words or dead air (the voice runs ahead of the
        picture). A clip spoken far faster or slower than the rest of the video is deleted so it is made again.
        meta gemini_audit false = off, gemini_audit_max = most clips re-made per run (default 6)."""
        if not meta.get("gemini_audit", True):
            return
        seen, rows = set(), []
        for l in lines:
            p = l["mp3"]
            if p in seen or l.get("edge_fb") or not p.exists() or p.stat().st_size == 0:
                continue
            seen.add(p)
            d = speech_seconds(p)
            t = l.get("vsay") or l["say"]
            rows.append((l, d, max(1, line_weight(t)), p.with_suffix(".aud").exists()))
        rates = sorted(w / d for l, d, w, aud in rows if d >= EMPTY_SECONDS and w >= 15)
        if len(rates) < 6:
            return
        med = rates[len(rates) // 2]
        flagged = []
        for l, d, w, aud in rows:
            if d < EMPTY_SECONDS:
                flagged.append((99.0, l))
            elif not aud and w >= 15:
                r = (w / d) / med
                if r > 2.2 or r < 1 / 2.2:
                    flagged.append((max(r, 1 / r), l))
        flagged.sort(key=lambda x: -x[0])
        cap = int(meta.get("gemini_audit_max", 6))
        if flagged:
            print(f"Gemini audit: {len(flagged)} saved clip(s) look wrong (speed far from the video's normal); "
                  f"re-making {min(cap, len(flagged))}", flush=True)
        for score, l in flagged[:cap]:
            print(f"    re-make: {l['say'][:50]}", flush=True)
            l["mp3"].unlink(missing_ok=True)

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
        if meta.get("speech_prep") and not fake:
            try:
                speech_prep(steps, meta, work, g_key)
            except Exception as e:           # never let the helper stop a video
                print(f"Speech prep skipped: {e}", flush=True)
        for s in steps:
            if "say" not in s:
                continue
            if s.get("prep"):
                s["prep_key"] = s["prep"].replace(SAY0, "").replace(SAY1, "")   # new wording -> new voice clip
                s["vsay"] = gemini_say(s["prep_key"], meta, s["prep"])
            else:
                s["vsay"] = gemini_say(s["say"], meta, s.get("say_m"))
            s["mp3"] = g_path(s)
            if g_edge_path(s).exists() and not (s["mp3"].exists() and s["mp3"].stat().st_size > 0):
                s["mp3"], s["edge_fb"] = g_edge_path(s), True  # Edge voice was used for this line in an earlier run
                continue
            if s.get("filler"):
                if s["mp3"] in seen:
                    continue  # same filler line used twice in one video: voice it once
                seen.add(s["mp3"])
                gk = ("filler", (len(seen) - 1) // 4)  # four filler lines per call
            else:
                mode = s["state"]["mode"]
                if mode in ("intro", "hook"):
                    gk = "intro"      # hook, preview line and own intro share one call (hook steps have no question number)
                elif mode == "outro":
                    gk = "outro"
                else:
                    gk = (s["state"]["i"] - 1) // g_batch
            if gk not in groups:
                groups[gk] = []
                order.append(gk)
            groups[gk].append(s)
        audit_cache([s for gk in order for s in groups[gk]])
        todo = [[s for s in groups[gk] if not (s["mp3"].exists() and s["mp3"].stat().st_size > 0)] for gk in order]
        todo = [t for t in todo if t]
        print(f"Gemini: {len(todo)} call group(s) to make, models: {', '.join(g_models)}", flush=True)
        made = []
        for n, lines in enumerate(todo, 1):
            print(f"  group {n}/{len(todo)} ({len(lines)} lines)", flush=True)
            await gemini_group(lines)
            made += lines
        # every clip made in this run must have real speech of a believable length; else once more alone, then Edge
        for l in made:
            if l.get("edge_fb"):
                continue
            if line_good(l):
                l["mp3"].with_suffix(".aud").touch()
            else:
                print(f"  Checking again, clip is empty or odd: {l['say'][:40]}...", flush=True)
                await gemini_line(l)

    async def one(s):
        if "say" not in s or s.get("edge_fb"):
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
        if src.get("edge_fb"):
            s["edge_fb"] = True


FIT_JS = """(limit) => {
  const f = document.getElementById('fit');
  let z = 1;
  f.style.zoom = z;
  while (f.getBoundingClientRect().height > limit && z > 0.55) { z -= 0.03; f.style.zoom = z; }
  return [z, f.getBoundingClientRect().height];
}"""


def render_images(meta, qs, steps, work, theme, layout, fmt, aspect="wide"):
    from playwright.sync_api import sync_playwright
    w, h = ASPECTS[aspect]
    cache = {}
    shrunk = []
    with sync_playwright() as p:
        try:  # the GitHub runner already has Google Chrome: no big browser download needed
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()  # Playwright's own Chromium
        page = browser.new_page(viewport={"width": w, "height": h})
        for n, s in enumerate(steps):
            key = json.dumps(s["state"], sort_keys=True)
            if key not in cache:
                img = work / "img" / f"{len(cache):04d}.png"
                page.set_content(page_html(meta, qs, s["state"], theme, layout, fmt, aspect))
                page.evaluate("document.fonts.ready")
                if aspect == "reel":
                    # rare safety net: a very long slide is shrunk until it stays above the bottom safe zone
                    z, height = page.evaluate(FIT_JS, h - REEL_TOP - REEL_BOTTOM)
                    if z < 1:
                        shrunk.append((s["state"].get("i", 0), s["state"]["mode"], z, height))
                page.screenshot(path=str(img))
                cache[key] = img
            s["img"] = cache[key]
        browser.close()
    for i, mode, z, height in shrunk:
        bad = height > h - REEL_TOP - REEL_BOTTOM
        print(f"{'WARNING' if bad else 'NOTE'} Q{i} {mode} slide shrunk to {z * 100:.0f}% to fit the reel safe zone"
              + (" and STILL too tall, shorten the text" if bad else ""))


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


REEL_HOOKS = [
    "❓ क्या आप इस प्रश्न का सही उत्तर जानते हैं?",
    "🧠 10 सेकंड में जवाब सोचिए!",
    "🔥 परीक्षा में बार-बार पूछा जाने वाला प्रश्न!",
    "✅ कितने प्रश्न आपके सही रहे? कमेंट करें!",
    "⚡ तेज़ रिवीज़न: ऐसे प्रश्न पक्का आएँगे!",
]
REEL_CTAS = [
    "💬 अपना उत्तर कमेंट में लिखिए। सही उत्तर और पॉइंट्स वीडियो में हैं 👆",
    "💬 कमेंट में अपना जवाब बताइए, फिर वीडियो में मिलाइए 👆",
    "💬 पहले जवाब सोचिए, फिर कमेंट कीजिए। उत्तर वीडियो में है 👆",
]
REEL_TAGS = ["#HaryanaGroupD", "#HSSCGroupD", "#HaryanaGK", "#HSSC", "#HaryanaExam", "#GKQuiz", "#SarkariNaukri", "#Target1st"]


def reel_caption(meta, qs):
    """Instagram caption for a reel, filled from the questions (no AI, no cost). Hindi, under 2200 characters.
    Optional meta: caption_hashtags (list), caption_extra (one line added before the hashtags),
    caption_hooks / caption_ctas (lists, replace the built-in rotating lines).
    The hook and call-to-action rotate by a hash of the title, so every reel reads a little different."""
    seed = int(hashlib.md5(str(meta.get("title", "")).encode("utf-8")).hexdigest(), 16)
    hooks = meta.get("caption_hooks") or REEL_HOOKS
    ctas = meta.get("caption_ctas") or REEL_CTAS
    tags = meta.get("caption_hashtags") or REEL_TAGS
    q = qs[0]
    qtext = q["q"] if len(q["q"]) <= 170 else q["q"][:167].rstrip() + "..."
    lines = [hooks[seed % len(hooks)], "", f"{meta['title']} | {len(qs)} प्रश्न", "",
             f"Q. {qtext}"]
    lines += [f"{l}) {t}" for l, t in zip("ABCD", q["options"])]
    lines += ["", ctas[(seed // 7) % len(ctas)], "",
              "📚 ग्रुप D के नोट्स और मॉक टेस्ट: लिंक बायो और हाइलाइट्स में।" if meta.get("promo") else "",
              f"📌 रोज़ ऐसे प्रश्नों के लिए {meta.get('channel', 'Target1st')} को फॉलो करें।",
              "📲 Telegram: @Target1stsupport"]
    if meta.get("caption_extra"):
        lines += [str(meta["caption_extra"])]
    lines += ["", " ".join(tags[:12])]
    text = "\n".join(lines)
    return text if len(text) <= 2200 else text[:2190].rstrip() + "..."


def sync_report(mp4, planned, timeline, meta):
    """Prints how long the voice and the picture really are, and lists any clip whose speed is far from the rest
    (those are the places where the voice can run ahead of the picture). Exits if voice and picture differ."""
    info = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(mp4)])
    dur = {}
    for ln in info.split():
        kind, _, val = ln.partition(",")
        try:
            dur[kind] = float(val)
        except ValueError:
            pass
    a, v = dur.get("audio", 0.0), dur.get("video", 0.0)
    print(f"SYNC CHECK: planned {planned:.2f}s | voice {a:.2f}s | picture {v:.2f}s | difference {abs(a - v) * 1000:.0f} ms",
          flush=True)
    rates = sorted(w / max(0.1, d) for _, d, _, w, fb in timeline if w >= 15 and not fb)
    if len(rates) >= 6:
        med = rates[len(rates) // 2]
        odd = [(st, d, tx) for st, d, tx, w, fb in timeline
               if w >= 15 and not fb and not (1 / 2.2 <= (w / max(0.1, d)) / med <= 2.2)]
        for st, d, tx in odd[:12]:
            print(f"  CHECK AT {fmt_time(st)} ({st:.1f}s): this line is spoken much faster/slower than the rest "
                  f"({d:.1f}s): {tx[:50]}", flush=True)
        if odd:
            print(f"  {len(odd)} line(s) to listen to. Delete their clip in work/audio (or leave meta gemini_audit on) "
                  "and re-run to have them voiced again.", flush=True)
    fb = [tx for _, _, tx, _, f in timeline if f]
    if fb:
        print(f"  {len(fb)} line(s) voiced by Edge because Gemini returned nothing: "
              + " | ".join(x[:30] for x in fb[:5]), flush=True)
    if abs(a - v) > float(meta.get("sync_tolerance", 0.25)):
        sys.exit(f"Voice ({a:.2f}s) and picture ({v:.2f}s) differ by more than "
                 f"{meta.get('sync_tolerance', 0.25)}s. Not publishing a video that is out of sync.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--out", default="output")
    ap.add_argument("--limit", type=int, default=0, help="only first N questions (0 = all)")
    ap.add_argument("--theme", default=None)
    ap.add_argument("--layout", default=None)
    ap.add_argument("--aspect", default=None, help="wide (1920x1080, YouTube) | reel (1080x1920, Instagram); default: meta 'aspect', else wide")
    ap.add_argument("--format", default=None)
    ap.add_argument("--tts", default=None, help="edge | gemini | sarvam (default: meta 'tts', else edge)")
    ap.add_argument("--fake-tts", action="store_true", help="silent placeholder audio, for layout tests")
    ap.add_argument("--no-fx", action="store_true", help="reels: plain slides, no zoom / highlight / sound effects (same as meta fx false)")
    a = ap.parse_args()

    data = json.loads(Path(a.json_file).read_text(encoding="utf-8"))
    meta = data["meta"]
    theme = pick(a.theme, meta.get("theme"), "classic", list(THEMES))
    layout = pick(a.layout, meta.get("layout"), "list", ["list", "grid"])
    fmt = pick(a.format, meta.get("format"), "quiz", ["quiz", "revision"])
    aspect_names = {"9:16": "reel", "vertical": "reel", "reels": "reel", "16:9": "wide", "landscape": "wide"}
    aspect = str(a.aspect if a.aspect and a.aspect != "auto" else (meta.get("aspect") or "wide")).strip().lower()
    aspect = aspect_names.get(aspect, aspect)
    if aspect not in ASPECTS:
        sys.exit(f"Invalid aspect '{aspect}'. Allowed: wide, reel")
    provider = pick(a.tts, meta.get("tts"), "edge", ["edge", "gemini", "sarvam"])
    long_fx = aspect == "wide" and bool(meta.get("long_fx", True)) and not a.no_fx
    qs, steps = make_steps(data, a.limit, fmt, aspect, long_fx)

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

    print(f"{len(qs)} questions, {len(steps)} steps | theme={theme} layout={'list (reel)' if aspect == 'reel' else layout} format={fmt} aspect={aspect} tts={provider}")
    asyncio.run(tts_all(steps, meta, work, a.fake_tts, provider))
    # Gemini has no speed setting: speed it up here (pitch is preserved by atempo, valid range 0.5-2.0)
    speed = float(meta.get("gemini_speed", 1.3)) if provider == "gemini" and not a.fake_tts else 1.0
    tempo = f",atempo={speed:.3f}" if speed != 1.0 else ""
    # Gemini sometimes leaves long dead air inside a line: shorten any pause over 0.45 s (meta gemini_squeeze, 0 = off)
    sq = float(meta.get("gemini_squeeze", 0.2)) if provider == "gemini" and not a.fake_tts else 0
    squeeze = (f",silenceremove=stop_periods=-1:stop_duration=0.45:stop_threshold=-45dB:stop_silence={sq:.2f}"
               if sq > 0 else "")
    # exact-length audio per step, then concat
    pause = float(meta.get("pause", PAUSE_DEFAULT))
    t = 0.0
    chapters = []
    wav_lines = []
    timeline = []    # (start, length, text, weight) of every voiced step, for the sync report
    for n, s in enumerate(steps):
        wav = work / "wav" / f"{n:04d}.wav"
        if "silence" in s:
            dur = s["silence"]
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                 "-t", f"{dur:.3f}", str(wav)])
        else:
            own = s.get("edge_fb")  # a line voiced by Edge keeps its own speed and is not squeezed
            run(["ffmpeg", "-y", "-i", str(s["mp3"]), "-af",
                 f"{TRIM}{'' if own else squeeze}{'' if own else tempo},apad=pad_dur={pause:.3f}"
                 + (f",apad=whole_dur={s['min_dur']:.3f}" if s.get("min_dur") else ""),
                 "-ar", "48000", "-ac", "1", str(wav)])
            dur = probe(wav)
            if dur < 0.3:
                sys.exit(f"Voice clip came out empty for: {s['say'][:60]}")
        if "chapter" in s:
            chapters.append((t, s["chapter"]))
        s["t"], s["dur"], s["pause"] = t, dur, pause
        wav_lines.append(f"file '{wav.resolve()}'")
        if "say" in s and "silence" not in s and not s.get("min_dur"):
            timeline.append((t, dur - pause, s["say"], line_weight(s.get("vsay") or s["say"]), bool(s.get("edge_fb"))))
        t += dur
    (work / "audio.txt").write_text("\n".join(wav_lines))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "audio.txt"),
         "-c", "copy", str(work / "audio.wav")])
    mp4 = out / "video.mp4"
    made = False
    # Reels get the retention effects (fx.py: hook card, camera zoom, word highlight, countdown ring, progress bar,
    # sound, loop). If anything goes wrong there the plain reel below is built instead, so the voice is never wasted.
    if ((aspect == "reel" and meta.get("fx", True)) or long_fx) and not a.no_fx:
        try:
            import fx
            kind = "reel" if aspect == "reel" else "long"
            print(f"{'Reel' if kind == 'reel' else 'Video'} effects: on", flush=True)
            fx.build_reel(sys.modules[__name__], meta, qs, steps, work, theme, fmt, mp4, work / "audio.wav", t,
                          kind, layout)
            made = True
        except (Exception, SystemExit) as e:
            print(f"WARNING: reel effects failed, building the plain reel instead.\n{e}", flush=True)
    if not made:
        render_images(meta, qs, steps, work, theme, layout, fmt, aspect)
        img_lines, f_prev = [], 0   # picture changes sit on exact frame boundaries so rounding never adds up
        for s in steps:
            f_end = max(f_prev + 1, round((s["t"] + s["dur"]) * FPS))
            img_lines += [f"file '{s['img'].resolve()}'", f"duration {(f_end - f_prev) / FPS:.5f}"]
            f_prev = f_end
        img_lines.append(f"file '{steps[-1]['img'].resolve()}'")
        (work / "images.txt").write_text("\n".join(img_lines))
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "images.txt"),
             "-i", str(work / "audio.wav"), "-vf", f"fps={FPS},format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4)])

    sync_report(mp4, t, timeline, meta)

    title = (f'{meta["title"]} {meta.get("subtitle", "")} | {len(qs)} Questions with Answer & '
             f'Explanation | {meta.get("channel", "Target1st")}')
    desc = [title, "", "Chapters:"] + [f"{fmt_time(c)} {name}" for c, name in chapters]
    (out / "description.txt").write_text("\n".join(desc), encoding="utf-8")
    if aspect == "reel":
        (out / "caption.txt").write_text(reel_caption(meta, qs), encoding="utf-8")
        print(f"Instagram caption written: {out / 'caption.txt'}")
    if meta.get("story") and t > 60:
        print(f"::warning::This story is {fmt_time(t)} long; Instagram accepts stories of 60 s at most. Use a shorter question or fewer points.")
    print(f"Done: {mp4}  ({fmt_time(t)} long)")


if __name__ == "__main__":
    main()
