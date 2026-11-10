#!/usr/bin/env python3
"""Target1st quiz video builder.

questions.json -> voice (Edge-TTS or Gemini AI voice) -> HTML slides (Playwright screenshots) -> one MP4 (FFmpeg).

Usage:
    python build.py questions.json --out output [--limit 2] [--theme night] [--layout grid]
                                    [--format revision] [--tts gemini] [--fake-tts]

theme:  classic | night | royal
layout: list | grid        (how the 4 options look on the question slide)
format: quiz | revision    (quiz = options + countdown; revision = question then answer, no countdown)
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
      gemini_model  default "gemini-3.1-flash-tts-preview" (copy the exact TTS model name from AI Studio if it 404s)
      gemini_style  instruction spoken-style prefix, default "Say in a clear, natural, energetic Hindi teacher voice"
      gemini_speed  default 1.3 (Gemini has no speed setting, FFmpeg speeds it up, pitch is kept; "rate" is Edge only)
      gemini_delay  seconds to wait between calls, default 6 (free tier is rate limited)
    Calls run one at a time with retries. Every finished line is cached in <out>/work/audio, so a run stopped by
    the free daily limit can be re-run to continue. If Gemini quality is not better than Edge, just use edge.

SARVAM VOICE (Bulbul, built for Indian languages, Hindi = hi-IN)
    Set meta "tts": "sarvam" (or --tts sarvam) and provide the SARVAM_API_KEY environment variable
    (GitHub: repository secret SARVAM_API_KEY, wired in video.yml). New accounts get Rs 100 free credits.
    Optional meta keys:
      sarvam_model    default "bulbul:v3" (also "bulbul:v4-flash", cheaper; its speaker names differ, e.g. "ishita_hi_devotional")
      sarvam_speaker  default "shubh" (lowercase, must match the model; v3 also has aditya, ritu, priya, neha, rahul, pooja, ...)
      sarvam_pace     default 1.2, range 0.5-2.0 (Sarvam has its own speed control, "rate" is Edge only)
      sarvam_delay    seconds between calls, default 1 (limit is 60 requests/minute)
    Every finished line is cached in <out>/work/audio, so a re-run never pays twice for the same line.
"""
import argparse
import asyncio
import base64
import hashlib
import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

W, H, FPS = 1920, 1080, 30
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
            body += f'<div class="cd">{st["cd"]}</div>'
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


def make_steps(data, limit, fmt):
    meta = data["meta"]
    qs = data["questions"][:limit] if limit else data["questions"]
    cd = int(meta.get("countdown", 5))
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
        steps.append({"state": {"mode": "q", "i": i, "opts": False}, "say": q["q"], "chapter": f"Q{i}"})
        if fmt == "quiz":
            say_opts = " ".join(f"ऑप्शन {LET_SAY[l]}, {t}।" for l, t in zip("ABCD", opts))
            steps.append({"state": {"mode": "q", "i": i, "opts": True}, "say": say_opts})
            for n in range(cd, 0, -1):
                steps.append({"state": {"mode": "q", "i": i, "opts": True, "cd": n}, "silence": 1.0})
        steps.append({"state": {"mode": "answer", "i": i, "pts": 0},
                      "say": f"सही उत्तर है, ऑप्शन {LET_SAY[ans]}, {opts[idx]}।"})
        for k, p in enumerate(q["points"], 1):
            steps.append({"state": {"mode": "answer", "i": i, "pts": k}, "say": norm_point(p)["say"]})
        if q.get("trick"):
            steps.append({"state": {"mode": "trick", "i": i}, "say": "ट्रिक। " + norm_point(q["trick"])["say"]})
    outro = meta.get("outro") or ("तो दोस्तों, आज के लिए बस इतना ही। वीडियो पसंद आया हो तो लाइक करें "
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


GEMINI_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VOICE = "Kore"
GEMINI_STYLE = "Say in a clear, natural, energetic Hindi teacher voice"


def gemini_tts_once(text, voice, model, style, out_wav, api_key):
    """One Gemini TTS call -> 24 kHz mono 16-bit WAV at out_wav. Raises on any failure."""
    prompt = f"{style}: {text}" if style else text
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
    g_voice = meta.get("gemini_voice", GEMINI_VOICE)
    g_model = meta.get("gemini_model", GEMINI_MODEL)
    g_style = meta.get("gemini_style", GEMINI_STYLE)
    g_delay = float(meta.get("gemini_delay", 6))  # seconds between calls, free tier is rate limited
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

    async def gemini_one(s, path):
        async with g_lock:  # one call at a time + spacing
            last = None
            for attempt in range(6):
                try:
                    await asyncio.to_thread(gemini_tts_once, s["say"], g_voice, g_model, g_style, path, g_key)
                    await asyncio.sleep(g_delay)
                    return
                except urllib.error.HTTPError as e:
                    last = f"HTTP {e.code}: {e.read()[:200]!r}"
                    if e.code in (400, 401, 403, 404):  # bad key / model / request: retrying is pointless
                        break
                    wait = 20 * (attempt + 1)  # 429 or 5xx: back off
                except Exception as e:
                    last = e
                    wait = 5 * (attempt + 1)
                print(f"  Gemini retry {attempt + 1}/6 in {wait}s ({last})")
                await asyncio.sleep(wait)
            sys.exit(f"Gemini voice failed for: {s['say'][:60]}\n{last}\n"
                     "Finished lines are cached: re-run later (free quota resets daily) to continue.")

    async def one(s):
        if "say" not in s:
            return
        if provider == "gemini":
            key = hashlib.md5(f"gemini|{g_voice}|{g_model}|{g_style}|{s['say']}".encode()).hexdigest()
            mp3 = work / "audio" / f"{key}.wav"
        elif provider == "sarvam":
            key = hashlib.md5(f"sarvam|{s_model}|{s_speaker}|{s_pace}|{s['say']}".encode()).hexdigest()
            mp3 = work / "audio" / f"{key}.wav"
        else:
            key = hashlib.md5(f"{voice}|{rate}|{s['say']}".encode()).hexdigest()
            mp3 = work / "audio" / f"{key}.mp3"
        s["mp3"] = mp3
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        if provider == "gemini" and not fake:
            await gemini_one(s, mp3)
            return
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
                    await edge_tts.Communicate(s["say"], voice, rate=rate).save(str(mp3))
                if mp3.exists() and mp3.stat().st_size > 0:
                    return
            except Exception as e:  # network hiccup, retry
                last = e
                await asyncio.sleep(2 * (attempt + 1))
        sys.exit(f"Voice generation failed for: {s['say'][:60]}\n{last}")

    await asyncio.gather(*(one(s) for s in steps))


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

    out = Path(a.out)
    work = out / "work"
    for d in ("audio", "img", "wav"):
        (work / d).mkdir(parents=True, exist_ok=True)

    print(f"{len(qs)} questions, {len(steps)} steps | theme={theme} layout={layout} format={fmt} tts={provider}")
    asyncio.run(tts_all(steps, meta, work, a.fake_tts, provider))
    # Gemini has no speed setting: speed it up here (pitch is preserved by atempo, valid range 0.5-2.0)
    speed = float(meta.get("gemini_speed", 1.3)) if provider == "gemini" and not a.fake_tts else 1.0
    tempo = f",atempo={speed:.3f}" if speed != 1.0 else ""
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
            run(["ffmpeg", "-y", "-i", str(s["mp3"]), "-af", f"{TRIM}{tempo},apad=pad_dur={pause:.3f}",
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
