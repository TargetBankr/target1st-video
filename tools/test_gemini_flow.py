"""Offline test for the Gemini voice flow in build.py (no API key, no quota used).

Usage: python tools/test_gemini_flow.py build.py new hard      (scenarios: hard | swallow | swallow2)
A fake Gemini gives every line its own pitch, with long pauses inside lines and short gaps between lines, and
(swallow2) returns silence for some lines. The test checks every cut clip for words of OTHER lines.
"""
import sys, json, asyncio, importlib.util, zlib, wave, struct, math, random, shutil, subprocess, os, re
from pathlib import Path
modpath, tag, scen = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("b_"+tag, modpath); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
SR=24000; calls={"n":0}
def freq(text): return 200 + (zlib.crc32(text.encode()) % 50)*20
random.seed(5)
def fake_tts(prompt, voice, model, out_wav, key):
    calls["n"]+=1
    pcm=[]
    def tone(sec,f,amp=9000):
        n=int(sec*SR); return [int(amp*math.sin(2*math.pi*f*i/SR)) for i in range(n)]
    def sil(sec): return [0]*int(sec*SR)
    paras=prompt.split("\n\n")
    for k,pt in enumerate(paras):
        f=freq(pt)
        if (scen=="swallow" and ".ppt" in pt) or (scen=="swallow2" and "pptx" in pt):   # Gemini returns nothing for the dotted word -> whole paragraph silent
            pcm+=sil(0.16); continue
        parts=re.split(r"([,।:;])", pt)
        for part in parts:
            if part in (",","।",":",";"):
                pcm+=sil(random.uniform(0.35,0.55) if part!="," else random.uniform(0.3,0.5))
            elif part.strip():
                pcm+=tone(max(0.45,len(part)*0.07),f)
        pcm+=sil(0.16)                          # paragraph gap SHORTER than the pauses inside lines (the real problem)
    tmp=out_wav.with_suffix(".part")
    with wave.open(str(tmp),"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(SR);w.writeframes(struct.pack("<%dh"%len(pcm),*pcm))
    tmp.replace(out_wav)
b.gemini_tts_once=fake_tts
async def fake_edge(text,voice,rate,pitch,path):
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","lavfi","-i","sine=frequency=1500:sample_rate=24000","-t",str(max(1,len(text)*0.06)),str(path)],check=True)
if hasattr(b,"edge_save"): b.edge_save=fake_edge
os.environ["GEMINI_API_KEY_2"]="x"
data=json.load(open(str(__import__("pathlib").Path(__file__).resolve().parent.parent / "hartron1.done.json"),encoding="utf-8"))
data["meta"]["gemini_delay"]=0; data["meta"]["filler_lines"]=[]
if scen in ("swallow","swallow2"):
    data["questions"][2]["points"][1]="पुराना format .ppt था, अब pptx चलता है"
    data["questions"][4]["points"][0]="file .pdf में save करें: यह जरूरी है"
qs,steps=b.make_steps(data,8,"revision")
work=Path(__import__("tempfile").gettempdir())/f"t1st_work_{tag}_{scen}"; shutil.rmtree(work,ignore_errors=True); (work/"audio").mkdir(parents=True)
try:
    asyncio.run(b.tts_all(steps,data["meta"],work,False,"gemini"))
except SystemExit as e:
    print("EXIT",e)
# purity check
def read(path):
    r=subprocess.run(["ffmpeg","-loglevel","error","-i",str(path),"-f","s16le","-ac","1","-ar",str(SR),"-"],capture_output=True)
    d=r.stdout; return struct.unpack("<%dh"%(len(d)//2),d)
bad=0; total=0; empties=0; edge=0
for s in steps:
    if "say" not in s: continue
    total+=1
    if s.get("edge_fb"): edge+=1; continue
    p=s.get("mp3")
    if not p or not Path(p).exists(): empties+=1; continue
    x=read(p); exp=freq(s.get("vsay") or s["say"])
    win=480; act=0; wrong=0
    for i in range(0,len(x)-win,win):
        seg=x[i:i+win]
        if sum(1 for v in seg if abs(v)>200)/win<0.85: continue   # only windows fully inside a tone
        act+=1
        zc=sum(1 for j in range(1,len(seg)) if (seg[j-1]<0)!=(seg[j]<0)); f=zc/2/(win/SR)
        if abs(f-exp)>70: wrong+=1
    if act==0: empties+=1; print('  EMPTY CLIP:', s['say'][:40], round(len(x)/SR,2),'s')
    elif wrong*win/SR>0.12: bad+=1; print("  WRONG CONTENT %.2fs of other lines inside:"%(wrong*win/SR), s["say"][:40])
print(f"[{tag}/{scen}] lines {total} | wrong-content clips {bad} | empty clips {empties} | edge-fallback {edge} | gemini calls {calls['n']}")
