#!/usr/bin/env python3
"""Target1st quiz video builder.

questions.json -> Edge-TTS voice -> HTML slides (Playwright screenshots) -> one MP4 (FFmpeg).

Usage:
    python build.py questions.json --out output [--limit 2] [--theme night] [--layout grid]
                                    [--format revision] [--fake-tts]

theme:  classic | night | royal
layout: list | grid        (how the 4 options look on the question slide)
format: quiz | revision    (quiz = options + countdown; revision = question then answer, no countdown)
Each of these can also be set in the JSON "meta"; command-line values win.
"""
import argparse
import asyncio
import hashlib
import html
import json
import subprocess
import sys
from pathlib import Path

W, H, FPS = 1920, 1080, 30
PAD = 0.45  # silence after every spoken line, seconds
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


async def tts_all(steps, meta, work, fake):
    sem = asyncio.Semaphore(4)
    voice = meta.get("voice", "hi-IN-MadhurNeural")
    rate = meta.get("rate", "+0%")

    async def one(s):
        if "say" not in s:
            return
        key = hashlib.md5(f"{voice}|{rate}|{s['say']}".encode()).hexdigest()
        mp3 = work / "audio" / f"{key}.mp3"
        s["mp3"] = mp3
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        if fake:
            dur = max(1.5, len(s["say"]) * 0.075)
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                 "-t", f"{dur:.2f}", "-acodec", "libmp3lame", str(mp3)])
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
        browser = p.chromium.launch()
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


def pick(cli, meta_val, default, allowed):
    v = cli if cli and cli != "auto" else (meta_val or default)
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
    ap.add_argument("--fake-tts", action="store_true", help="silent placeholder audio, for layout tests")
    a = ap.parse_args()

    data = json.loads(Path(a.json_file).read_text(encoding="utf-8"))
    meta = data["meta"]
    theme = pick(a.theme, meta.get("theme"), "classic", list(THEMES))
    layout = pick(a.layout, meta.get("layout"), "list", ["list", "grid"])
    fmt = pick(a.format, meta.get("format"), "quiz", ["quiz", "revision"])
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

    print(f"{len(qs)} questions, {len(steps)} steps | theme={theme} layout={layout} format={fmt}")
    asyncio.run(tts_all(steps, meta, work, a.fake_tts))
    render_images(meta, qs, steps, work, theme, layout, fmt)

    # exact-length audio per step, then concat
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
            dur = probe(s["mp3"]) + PAD
            run(["ffmpeg", "-y", "-i", str(s["mp3"]), "-af", f"apad=whole_dur={dur:.3f}",
                 "-ar", "48000", "-ac", "1", str(wav)])
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
