#!/usr/bin/env python3
"""Retention effects for Instagram reels (aspect "reel"). Used by build.py, free, no new packages.

What it adds to a reel (everything is generated here with Chrome + FFmpeg, no stock files needed):
  1. Hook card at the start (big headline, designed first frame = the reel thumbnail) with a camera push-in.
  2. Camera movement: slow zoom in / out on every question scene, a punch-in at the answer reveal.
  3. Word-by-word highlight of the question, the points and the trick while they are spoken. The option that is being
     read lights up too.
  4. Countdown ring. Quiz: shrinks during the thinking seconds. Revision: shrinks while the options are being read.
  5. Progress bar across the top (whole reel) and a "प्रश्न 2 / 4" counter on every question.
  6. Sound: whoosh on the hook and every new question, tick per countdown second (quiz), ding on the answer,
     pop on the trick and on the QR codes, plus a soft background track (or your own file, see below).
  7. Seamless loop: the last 0.5 s dissolves back into the hook card, so Instagram's auto-replay looks continuous.

Switches in the JSON "meta" (all optional):
  fx              false = plain reel, no effects at all (default true for aspect reel)
  zoom            camera zoom amount, default 0.07 (0 = no camera movement); hook card uses a bit more
  progress_bar    false = no progress bar
  sfx             false = no sound effects
  sfx_volume      default 1.0 (scales every effect)
  music           false = no background track
  music_volume    default 0.08
  loop            false = no dissolve back to the hook at the end
Own background music: put .mp3 / .m4a / .wav / .ogg files in  assets/music/  (free: YouTube Audio Library, Pixabay Music).
One file is picked per reel (by the title) and looped under the voice. With no file there the built-in soft pad is used.

Long videos (aspect wide / YouTube) use the same file in a calmer mode (kind "long"): no camera zoom, no word highlight on
questions or points, ring bottom-right (quiz: thinking seconds, revision: while options are read), "प्रश्न 3 / 25"
counter, thin progress bar on top, a ding on the answer and a pop on the trick (the trick line is the only highlighted
text), a very quiet music bed (default 0.05), and the hook / checkpoint slides made by build.py. meta: long_fx false = off.

If anything in here fails, build.py prints a WARNING and builds the plain reel instead, so a build never gets lost.
"""
import array
import hashlib
import json
import math
import subprocess
import wave
from pathlib import Path

FPS = 30
SR = 48000
SCALE = 1.5          # screenshots are made 1.5x bigger so the zoom stays sharp
LEAD = 0.06          # a word lights up this many seconds before it is heard (reads better than late)
GRID = 0.1           # ring / countdown pictures per second = 10
POPS = [0.90, 1.05, 1.08, 1.03, 1.0]   # size of the green answer bar over its first frames
LOOP_FADE = 0.5

APPLY_JS = """(fx) => {
  if (fx.g) {
    document.querySelectorAll('.w[data-g="' + fx.g + '"]').forEach(e => {
      const i = +e.dataset.i;
      e.className = 'w' + (i < fx.n ? ' d' : (i === fx.n ? ' on' : ''));
      if (e.parentElement) e.parentElement.classList.toggle('live', fx.n < +e.parentElement.querySelectorAll('.w').length);
    });
  }
  if (fx.o !== undefined) {
    document.querySelectorAll('.opt').forEach((e, i) => e.classList.toggle('act', i === fx.o));
  }
  if (fx.ring !== undefined) {
    const c = document.getElementById('rc');
    if (c) { const L = parseFloat(c.getAttribute('stroke-dasharray')); c.style.strokeDashoffset = (L * (1 - fx.ring)).toFixed(2); }
    const t = document.getElementById('rn');
    if (t && fx.num !== undefined) t.textContent = fx.num;
  }
  if (fx.pop !== undefined) {
    const a = document.querySelector('.ans');
    if (a) a.style.transform = 'scale(' + fx.pop + ')';
  }
}"""


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(str(c) for c in cmd)[:300]}\n{r.stderr[-1200:]}")
    return r.stdout


# ---------------------------------------------------------------- what happens inside every step

def word_starts(words, span):
    """Start second of every word inside a spoken line of `span` seconds (longer words and words before a comma or
    danda take longer). No speech recognition needed: the text is known, only its timing is estimated."""
    w = [len(x) + 1 + (4 if x[-1:] in ",।.;:?!" else 0) for x in words]
    tot = float(sum(w)) or 1.0
    out, acc = [], 0
    for x in w:
        out.append(span * acc / tot)
        acc += x
    return out


def words_events(text, group, span):
    words = str(text).split()
    if not words:
        return [(0.0, {})], {}
    starts = word_starts(words, span)
    ev = [(max(0.0, t - LEAD), {"g": group, "n": k}) for k, t in enumerate(starts)]
    final = {"g": group, "n": len(words)}
    ev.append((span, final))
    return ev, final


def plan(bld, meta, qs, steps, fmt, kind="reel"):
    """For every step: the slide state to draw and the list of (seconds since the step started, fx state) changes."""
    cd_total = max(1, int(meta.get("countdown", 5)))
    reel = kind == "reel"
    grid = GRID if reel else 0.2
    plans = []
    last_final = {}
    for s in steps:
        st = dict(s["state"])
        mode = st["mode"]
        dur = s["dur"]
        sp = dur if "silence" in s else max(0.3, dur - s["pause"])
        ev, final = [(0.0, {})], {}
        if s.get("filler"):
            ev, final = [(0.0, last_final)], last_final
        elif mode == "q" and not st.get("opts"):
            if reel:
                ev, final = words_events(qs[st["i"] - 1]["q"], "q", sp)
        elif mode == "q" and st.get("cd"):
            n = int(st["cd"])
            st["rb"] = "show"
            ev = [(round(m * grid, 3), {"ring": max(0.0, (n - m * grid) / cd_total), "num": n})
                  for m in range(int(round(dur / grid)))]
            final = ev[-1][1]
        elif mode == "q":     # options are being read
            q = qs[st["i"] - 1]
            ring = fmt == "revision"
            st["rb"] = "show" if ring else "hide"
            wts = [9 + len(q["_osay"][k] or q["options"][k]) for k in range(4)]
            tot = float(sum(wts))
            starts, acc = [], 0
            for x in wts:
                starts.append(sp * acc / tot)
                acc += x
            ends = starts[1:] + [sp]

            def act(rel):
                for k in range(4):
                    if starts[k] - LEAD <= rel < ends[k]:
                        return k
                return -1
            times = {0.0, sp} | {max(0.0, x - LEAD) for x in starts}
            if ring:
                times |= {round(m * grid, 3) for m in range(int(dur / grid) + 1) if m * grid < dur}
            ev = []
            for rel in sorted(times):
                f = {"o": act(rel)} if reel else {}
                if ring:
                    f["ring"] = max(0.0, 1 - rel / dur)
                    f["num"] = max(1, math.ceil(dur - rel - 1e-6))
                ev.append((rel, f))
            final = ev[-1][1]
        elif mode == "answer" and st["pts"] == 0:
            ev = [(round(k * 0.05, 3), {"pop": v}) for k, v in enumerate(POPS)]
            final = {"pop": 1.0}
        elif mode == "answer" and reel:
            k = st["pts"]
            txt = bld.norm_point(qs[st["i"] - 1]["points"][k - 1])["show"]
            ev, final = words_events(txt, f"p{k}", sp)
        elif mode == "trick":
            txt = bld.norm_point(qs[st["i"] - 1]["trick"])["show"]
            ev, final = words_events(txt, "t", sp)
        plans.append({"state": st, "events": ev, "final": final})
        last_final = final
    return plans


# ---------------------------------------------------------------- pictures

def render_frames(bld, meta, qs, steps, plans, work, theme, fmt, kind="reel", layout="list"):
    """Draw every picture once. A step with several changes is drawn once and then only its highlight is switched."""
    from playwright.sync_api import sync_playwright
    reel = kind == "reel"
    w, h = bld.ASPECTS["reel" if reel else "wide"]
    imgdir = work / "fximg"
    imgdir.mkdir(parents=True, exist_ok=True)
    cache = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=SCALE if reel else 1)
        for s, pl in zip(steps, plans):
            st = pl["state"]
            # which fx states this step really shows (one per change, last one wins when two share a frame)
            frames = {}
            for rel, fxs in pl["events"]:
                k = min(s["f1"] - 1, max(s["f0"], s["f0"] + int(round(rel * FPS))))
                frames[k] = fxs
            if s["f0"] not in frames:
                frames[s["f0"]] = pl["events"][0][1]
            starts = sorted(frames)
            keys = [json.dumps([st, frames[k]], sort_keys=True) for k in starts]
            if any(k not in cache for k in keys):
                page.set_content(bld.page_html(meta, qs, st, theme, "list" if reel else layout, fmt,
                                               "reel" if reel else "wide", fx=True))
                page.evaluate("document.fonts.ready")
                z, height = page.evaluate(bld.FIT_JS, h - bld.REEL_TOP - bld.REEL_BOTTOM) if reel else (1, 0)
                if z < 1:
                    bad = height > h - bld.REEL_TOP - bld.REEL_BOTTOM
                    print(f"{'WARNING' if bad else 'NOTE'} Q{st.get('i', 0)} {st['mode']} slide shrunk to {z * 100:.0f}% "
                          f"to fit the reel safe zone" + (" and STILL too tall, shorten the text" if bad else ""), flush=True)
                for k, key in zip(starts, keys):
                    if key in cache:
                        continue
                    if frames[k]:
                        page.evaluate(APPLY_JS, frames[k])
                    path = imgdir / f"{len(cache):05d}.png"
                    page.screenshot(path=str(path))
                    cache[key] = path
            ends = starts[1:] + [s["f1"]]
            s["items"] = [(cache[key], e - b) for key, b, e in zip(keys, starts, ends)]
        browser.close()
    print(f"Effects: {len(cache)} pictures drawn", flush=True)


# ---------------------------------------------------------------- video (scenes: zoom per question)

def scenes(steps):
    out = []
    for s in steps:
        m = s["state"]["mode"]
        key = "intro" if m == "intro" else ("end" if m in ("promo", "outro") else f"q{s['state']['i']}")
        if out and out[-1]["key"] == key:
            out[-1]["steps"].append(s)
        else:
            out.append({"key": key, "steps": [s]})
    return out


def write_concat(path, items):
    lines = []
    for img, fr in items:
        lines += [f"file '{Path(img).resolve()}'", f"duration {fr / FPS:.6f}"]
    lines.append(f"file '{Path(items[-1][0]).resolve()}'")   # the demuxer ignores the last duration without this
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def zoom_expr(n, zm, zoom_in, punches, amp=0.045, pf=9):
    """z for zoompan: smooth push in (or out) over the whole scene plus a short punch-in at each given frame."""
    base = f"st(0,min(1,on/{max(1, n - 1)}));st(1,ld(0)*ld(0)*(3-2*ld(0)));"
    z = base + (f"1+{zm:.4f}*ld(1)" if zoom_in else f"1+{zm:.4f}*(1-ld(1))")
    for a in punches:
        z += f"+{amp:.4f}*gte(on,{a})*max(0,1-(on-{a})/{pf})"
    return z


def build_video_long(bld, meta, steps, work, theme, out_mp4, voice_mix, total_frames):
    """YouTube: one pass, no camera movement. Pictures + progress bar on top + the mixed sound."""
    fxd = work / "fx"
    fxd.mkdir(parents=True, exist_ok=True)
    items = [it for s in steps for it in s["items"]]
    write_concat(fxd / "all.txt", items)
    total = total_frames / FPS
    th = bld.THEMES[theme]
    fill = "0x" + th["q"].lstrip("#")
    track = "white@0.28" if theme == "night" else "black@0.2"
    # small QR in the corner for the whole video (meta qr / qr_url); hidden while the big QR slide is on screen
    qr_in, qr_fc = [], ""
    links = bld.qr_list(meta) if meta.get("qr_corner", True) else []
    if links:
        qpng = fxd / "qr_corner.png"
        qpng.write_bytes(bld.qr_png_bytes(links[0]["url"]))
        size = int(meta.get("qr_corner_size", 170))
        pos = {"bl": "30:H-h-30", "br": "W-w-30:H-h-30", "tl": "30:30", "tr": "W-w-30:30"}[meta.get("qr_corner_pos", "bl")]
        hide = "".join(f"+between(t,{s['t']:.3f},{s['t'] + s['dur']:.3f})" for s in steps if s["state"]["mode"] == "qrcta")
        en = f":enable='not(0{hide})'" if hide else ""
        qr_in = ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", qpng]
        qr_fc = f"[2:v]scale={size}:{size}[qrs];[vq][qrs]overlay={pos}{en}"
    if meta.get("progress_bar", True):
        fc = (f"color=c={track}:s=1920x10:r={FPS},format=rgba[tr];color=c={fill}:s=1920x10:r={FPS},format=rgba[fl];"
              f"[tr][fl]overlay=x='-1920+1920*t/{total:.3f}':y=0:eval=frame:shortest=1[hud];"
              f"[0:v]fps={FPS},format=yuv420p[b];[b][hud]overlay=0:0:shortest=1[vq]")
    else:
        fc = f"[0:v]fps={FPS},format=yuv420p[vq]"
    fc += (";" + qr_fc + ",format=yuv420p[v]") if qr_fc else ";[vq]format=yuv420p[v]"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", fxd / "all.txt", "-i", voice_mix] + qr_in + ["-filter_complex", fc,
         "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-r", FPS, "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", "-movflags", "+faststart", out_mp4])


def build_video(bld, meta, steps, work, theme, out_mp4, voice_mix, total_frames):
    fxd = work / "fx"
    fxd.mkdir(parents=True, exist_ok=True)
    zoom = float(meta.get("zoom", 0.07))
    segs = []
    sc = scenes(steps)
    hook_img = steps[0]["items"][0][0]
    for k, scene in enumerate(sc):
        items = [it for s in scene["steps"] for it in s["items"]]
        n = sum(fr for _, fr in items)
        lst = fxd / f"scene{k:02d}.txt"
        seg = fxd / f"scene{k:02d}.mp4"
        write_concat(lst, items)
        enc = ["-frames:v", n, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", FPS]
        if scene["key"] == "end":
            length = n / FPS
            if meta.get("loop", True) and length >= 1.0:
                run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-loop", "1", "-framerate", FPS,
                     "-t", f"{LOOP_FADE + 0.2:.2f}", "-i", hook_img, "-filter_complex",
                     f"[0:v]fps={FPS},scale=1080:1920:flags=lanczos,format=yuv420p,settb=AVTB[a];"
                     f"[1:v]fps={FPS},scale=1080:1920:flags=lanczos,format=yuv420p,settb=AVTB[b];"
                     f"[a][b]xfade=transition=fade:duration={LOOP_FADE}:offset={length - LOOP_FADE:.3f}[v]",
                     "-map", "[v]"] + enc + [seg])
            else:
                run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf",
                     f"fps={FPS},scale=1080:1920:flags=lanczos,format=yuv420p"] + enc + [seg])
        elif zoom > 0:
            if scene["key"] == "intro":
                zm, zin, punches = zoom * 1.5, True, []
            else:
                qi = int(scene["key"][1:])
                zm, zin = zoom, qi % 2 == 1
                punches = []
                for s in scene["steps"]:
                    st = s["state"]
                    if st["mode"] == "answer" and st["pts"] == 0 and not s.get("filler"):
                        punches.append(s["f0"] - scene["steps"][0]["f0"])
            z = zoom_expr(n, zm, zin, punches)
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf",
                 f"fps={FPS},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps={FPS},"
                 f"format=yuv420p"] + enc + [seg])
        else:
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf",
                 f"fps={FPS},scale=1080:1920:flags=lanczos,format=yuv420p"] + enc + [seg])
        segs.append(seg)
        print(f"  scene {scene['key']}: {n} frames", flush=True)
    (fxd / "segs.txt").write_text("\n".join(f"file '{p.resolve()}'" for p in segs), encoding="utf-8")

    total = total_frames / FPS
    th = bld.THEMES[theme]
    fill = "0x" + th["q"].lstrip("#")
    track = "white@0.28" if theme == "night" else "black@0.2"
    if meta.get("progress_bar", True):
        fc = (f"color=c={track}:s=900x10:r={FPS},format=rgba[tr];color=c={fill}:s=900x10:r={FPS},format=rgba[fl];"
              f"[tr][fl]overlay=x='-900+900*t/{total:.3f}':y=0:eval=frame:shortest=1[hud];"
              f"[0:v]format=yuv420p[b];[b][hud]overlay=60:96:shortest=1,format=yuv420p[v]")
    else:
        fc = "[0:v]format=yuv420p[v]"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", fxd / "segs.txt", "-i", voice_mix, "-filter_complex", fc,
         "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
         "-r", FPS, "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", "-movflags", "+faststart", out_mp4])


# ---------------------------------------------------------------- sound

SFX_DEF = {   # name: (ffmpeg lavfi source, seconds)
    "tick": ("aevalsrc=exprs='0.8*sin(2*PI*1500*t)*exp(-60*t)':d=0.12:s=48000", 0.12),
    "ding": ("aevalsrc=exprs='(0.6*sin(2*PI*1319*t)+0.4*sin(2*PI*1976*t)+0.2*sin(2*PI*2637*t))*exp(-8*t)':d=0.6:s=48000", 0.6),
    "pop": ("aevalsrc=exprs='sin(2*PI*(260+1400*t)*t)*exp(-28*t)':d=0.2:s=48000", 0.2),
    "whoosh": ("anoisesrc=d=0.7:c=pink:r=48000:a=0.7,highpass=f=300,lowpass=f=4500,"
               "afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35,volume=1.3", 0.7),
}


def make_sfx(work):
    d = work / "sfx"
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, (src, _) in SFX_DEF.items():
        f = d / f"{name}.wav"
        if not f.exists():
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-ac", 1, "-ar", SR, "-c:a", "pcm_s16le", f])
        with wave.open(str(f)) as w:
            a = array.array("h")
            a.frombytes(w.readframes(w.getnframes()))
        out[name] = a
    return out


def sfx_events(meta, steps, kind="reel"):
    ev = []
    for s in steps:
        st, t = s["state"], s["t"]
        if s.get("filler"):
            continue
        m = st["mode"]
        if kind == "long":   # calm: a soft whoosh on the hook, a pop on checkpoint and trick, a ding on every answer
            if m == "hook" and st.get("stage") == 0:
                ev.append((t, "whoosh", 0.35))
            elif m in ("check", "qrcta"):
                ev.append((t, "pop", 0.35))
            elif m == "answer" and st["pts"] == 0:
                ev.append((t, "ding", 0.35))
            elif m == "trick":
                ev.append((t, "pop", 0.28))
            continue
        if m == "intro":
            ev.append((0.0, "whoosh", 0.55))
        elif m == "q" and not st.get("opts"):
            ev.append((t, "whoosh", 0.30))
        elif m == "q" and st.get("cd"):
            ev.append((t, "tick", 0.55))
        elif m == "answer" and st["pts"] == 0:
            ev.append((t, "ding", 0.45))
        elif m == "trick":
            ev.append((t, "pop", 0.40))
        elif m == "promo" and st.get("a") == 1 and st.get("b") == 0:
            ev.append((t, "pop", 0.45))
        elif m == "promo" and st.get("b") == 1:
            ev.append((t, "pop", 0.45))
    return ev


def mix_sfx(meta, steps, work, total, kind="reel"):
    n = int(total * SR) + SR
    track = array.array("h", bytes(2 * n))
    if meta.get("sfx", True):
        snd = make_sfx(work)
        vol = float(meta.get("sfx_volume", 1.0))
        for t, name, v in sfx_events(meta, steps, kind):
            off = int(t * SR)
            a = snd[name]
            g = v * vol
            for k in range(min(len(a), n - off)):
                x = track[off + k] + int(a[k] * g)
                track[off + k] = 32767 if x > 32767 else (-32768 if x < -32768 else x)
    path = work / "sfx.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(track.tobytes())
    return path


def music_input(meta, work, total):
    """(ffmpeg input args, file) for the background track, or None."""
    if meta.get("music", True) is False:
        return None
    folder = Path(__file__).resolve().parent / "assets" / "music"
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg", ".aac")) \
        if folder.is_dir() else []
    if files:
        pick = files[int(hashlib.md5(str(meta.get("title", "")).encode("utf-8")).hexdigest(), 16) % len(files)]
        print(f"Music: {pick.name}", flush=True)
        return ["-stream_loop", "-1", "-i", pick]
    f = work / "music.wav"
    expr = ("0.07*(sin(2*PI*220*t)+sin(2*PI*261.63*t)+sin(2*PI*329.63*t)+0.6*sin(2*PI*440*t))*(0.75+0.25*sin(2*PI*0.18*t))"
            "+0.22*sin(2*PI*55*t)*exp(-7*mod(t,0.625))+0.05*sin(2*PI*110*t)")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"aevalsrc=exprs='{expr}':d={total + 2:.2f}:s={SR}", "-ac", 1,
         "-c:a", "pcm_s16le", f])
    return ["-i", f]


def mix_audio(meta, steps, work, voice_wav, total, kind="reel"):
    sfx = mix_sfx(meta, steps, work, total, kind)
    mus = music_input(meta, work, total)
    out = work / "mix.wav"
    mv = float(meta.get("music_volume", 0.08 if kind == "reel" else 0.05))
    cmd = ["ffmpeg", "-y", "-i", voice_wav, "-i", sfx] + (mus or [])
    if mus:
        fc = (f"[0:a]aresample={SR}[v];[1:a]aresample={SR}[s];"
              f"[2:a]aresample={SR},atrim=0:{total:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=1.0,"
              f"afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5,volume={mv}[m];"
              f"[v][s][m]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        fc = (f"[0:a]aresample={SR}[v];[1:a]aresample={SR}[s];"
              f"[v][s]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    run(cmd + ["-filter_complex", fc, "-map", "[a]", "-ar", SR, "-ac", 1, "-c:a", "pcm_s16le", out])
    return out


# ---------------------------------------------------------------- entry point

def build_reel(bld, meta, qs, steps, work, theme, fmt, out_mp4, voice_wav, total, kind="reel", layout="list"):
    """steps need s["t"], s["dur"], s["pause"] (set by build.py). Writes out_mp4 with the voice mixed with sound effects."""
    f_prev = 0
    for s in steps:
        f_end = max(f_prev + 1, round((s["t"] + s["dur"]) * FPS))
        s["f0"], s["f1"] = f_prev, f_end
        f_prev = f_end
    total_frames = f_prev
    plans = plan(bld, meta, qs, steps, fmt, kind)
    render_frames(bld, meta, qs, steps, plans, work, theme, fmt, kind, layout)
    mix = mix_audio(meta, steps, work, voice_wav, total, kind)
    if kind == "long":
        build_video_long(bld, meta, steps, work, theme, out_mp4, mix, total_frames)
    else:
        build_video(bld, meta, steps, work, theme, out_mp4, mix, total_frames)
