#!/usr/bin/env python3
"""Daily current-affairs question JSON, made automatically for Target1st (Haryana + SSC focus).

    news feeds (RSS)  ->  Gemini writes MCQs ONLY from those headlines  ->  checks  ->  daily/currentaffairs-<date>.done.json

The file name ends in .done.json, so video.yml builds the video from it (daily-currentaffairs.yml starts that build itself,
because a push made with the workflow's own token does not trigger other workflows).

    python tools/make_daily_ca.py                      # today's file (India date), 15 questions
    python tools/make_daily_ca.py --count 10 --date 2026-11-22
    python tools/make_daily_ca.py --dry-run            # print the headlines and the prompt, call nothing
    python tools/make_daily_ca.py --fake               # no network at all: a built-in sample, to test the checks and the file

Needs (GitHub: repository secrets, same names as video.yml): GEMINI_API_KEY, or GEMINI_API_KEY_2 ... with --key-slot 2.
Standard library only, no pip install.

Besides the JSON it writes  daily/currentaffairs-<date>.sources.txt  (headline behind every run, for your 2-minute morning check).
That file is not a .done.json, so it never triggers a build.
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# (label, url, how many newest items to keep). Edit freely: a feed that fails is skipped, the run continues.
# Google News RSS gives Haryana and SSC-style searches in Hindi without needing a site-specific feed.
GN = "https://news.google.com/rss/search?hl=hi&gl=IN&ceid=IN:hi&q="
FEEDS = [
    ("PIB (Hindi)",        "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3", 25),
    ("The Hindu National", "https://www.thehindu.com/news/national/feeder/default.rss", 20),
    ("The Hindu Business", "https://www.thehindu.com/business/feeder/default.rss", 10),
    ("Indian Express",     "https://indianexpress.com/section/india/feed/", 15),
    ("Haryana news",       GN + urllib.parse.quote("हरियाणा सरकार OR हरियाणा योजना when:2d"), 20),
    ("Haryana (English)",  "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
                           + urllib.parse.quote("Haryana government scheme OR Haryana appointed when:2d"), 15),
    ("Awards/Appointments", GN + urllib.parse.quote("नियुक्त OR पुरस्कार OR सम्मान भारत when:2d"), 15),
    ("Sports",             GN + urllib.parse.quote("खेल भारत जीता OR स्वर्ण when:2d"), 10),
]
MAX_AGE_HOURS = 60
MAX_HEADLINES = 90

MODELS = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]   # tried in order, same list build.py uses for speech prep

# Same look and voice settings as your other videos. tts "edge" is free; change to "sarvam" (and key_slot) for the paid voice.
META = {
    "subtitle": "SSC, HSSC, हरियाणा पुलिस और सभी परीक्षाओं के लिए",
    "channel": "Target1st",
    "voice": "hi-IN-MadhurNeural",
    "rate": "+20%",
    "countdown": 0,
    "intro": "o",
    "outro": "o",
    "outro_show": "देखने के लिए धन्यवाद!",
    "theme": "royal",
    "layout": "grid",
    "format": "revision",
    "tts": "edge",
    "pronounce": {"RBI": "आर बी आई", "SBI": "एस बी आई", "UPSC": "यू पी एस सी", "GDP": "जी डी पी",
                  "ISRO": "इसरो", "NITI": "नीति", "PIB": "पी आई बी"},
    "max_points": 2,
    "checkpoint_every": 10,
    "checkpoint_secs": 9,
}

PROMPT = """तुम Target1st के लिए HSSC CET / Group D / SSC / हरियाणा पुलिस / बैंकिंग परीक्षाओं के करंट अफेयर्स प्रश्न बनाने वाले विशेषज्ञ हो।

नीचे आज की खबरों की हेडलाइन हैं (स्रोत सहित)। इन्हीं से {n} बहुविकल्पीय प्रश्न (MCQ) बनाओ।

सख्त नियम:
1. सिर्फ़ नीचे दी गई हेडलाइन में लिखी जानकारी से प्रश्न बनाओ। अपनी तरफ़ से कोई तथ्य, तारीख़, आँकड़ा या नाम मत जोड़ो। अगर किसी हेडलाइन से पक्का उत्तर नहीं निकलता, उसे छोड़ दो।
2. कम से कम {h} प्रश्न हरियाणा से जुड़े हों (जितने हेडलाइन मिलें), बाकी राष्ट्रीय/अंतरराष्ट्रीय/खेल/पुरस्कार/नियुक्ति/योजना/अर्थव्यवस्था से। ऐसे विषय चुनो जो परीक्षा में पूछे जा सकते हैं। राजनीतिक विवाद, अपराध की ख़बरें और अफवाहें छोड़ दो।
3. भाषा सरल हिंदी। प्रश्न एक वाक्य, हर विकल्प छोटा। 4 विकल्प, गलत विकल्प भी असली और भ्रमित करने वाले हों।
4. हर प्रश्न का "answer" सिर्फ़ A, B, C या D हो, और सही उत्तर अलग-अलग अक्षरों पर आए।
5. हर प्रश्न में "points" में 2 छोटे बिंदु हों (हर बिंदु 12 शब्द से कम), जो हेडलाइन की जानकारी से ही हों।
6. हर प्रश्न में "src" में उस हेडलाइन का नंबर लिखो जिससे वह बना है।
7. एक ही ख़बर से दो प्रश्न मत बनाओ।

सिर्फ़ यह JSON लौटाओ, और कुछ नहीं:
{{"questions": [{{"q": "...", "options": ["...", "...", "...", "..."], "answer": "A", "points": ["...", "..."], "src": 3}}]}}

हेडलाइन:
{heads}
"""


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------------------------------------- news

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Target1st daily CA bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feed(raw):
    """RSS 2.0 or Atom -> list of (title, datetime or None)."""
    root = ET.fromstring(raw)
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title, when = "", None
        for ch in it:
            t = ch.tag.split("}")[-1]
            if t == "title" and ch.text:
                title = html.unescape(re.sub(r"<[^>]+>", "", ch.text)).strip()
            elif t in ("pubDate", "published", "updated", "date") and ch.text and when is None:
                try:
                    when = email.utils.parsedate_to_datetime(ch.text.strip())
                except Exception:
                    try:
                        when = dt.datetime.fromisoformat(ch.text.strip().replace("Z", "+00:00"))
                    except Exception:
                        when = None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        if title:
            out.append((title, when))
    return out


def norm_title(t):
    t = re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", t)      # drop the " - Publisher" tail Google News adds
    return re.sub(r"[^\wऀ-ॿ]+", " ", t).strip().lower()


def collect_headlines():
    now = dt.datetime.now(dt.timezone.utc)
    seen, heads = set(), []
    for label, url, keep in FEEDS:
        try:
            items = parse_feed(http_get(url))
        except Exception as e:
            log(f"  feed skipped ({label}): {type(e).__name__}: {e}")
            continue
        n = 0
        for title, when in items:
            if n >= keep:
                break
            if when is not None and (now - when).total_seconds() > MAX_AGE_HOURS * 3600:
                continue
            key = norm_title(title)
            if len(key) < 12 or key in seen:
                continue
            seen.add(key)
            heads.append((label, re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", title)))
            n += 1
        log(f"  {label}: {n} headlines")
    return heads[:MAX_HEADLINES]


# ----------------------------------------------------------------------------------------------- Gemini

def gemini_json(prompt, key, models):
    """Ask Gemini for JSON. Tries each model in order; returns the parsed dict or raises."""
    last = None
    for model in models:
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                text = resp["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                return json.loads(text)
            except urllib.error.HTTPError as e:
                last = f"{model}: HTTP {e.code}"
                if e.code in (429, 500, 503) and attempt == 0:
                    time.sleep(20)
                    continue
                break           # 404 (no such model), 400, 403...: next model
            except Exception as e:
                last = f"{model}: {type(e).__name__}: {e}"
                break
        log(f"  model failed: {last}")
    raise RuntimeError(f"no Gemini model answered ({last})")


# ----------------------------------------------------------------------------------------------- checks

def clean_questions(data, nheads):
    """Return (good, problems). Anything not fully valid is dropped, never repaired by guessing."""
    good, problems, seen = [], [], set()
    for i, q in enumerate(data.get("questions", []), 1):
        try:
            text = str(q["q"]).strip()
            opts = [str(o).strip() for o in q["options"]]
            ans = str(q["answer"]).strip().upper()[:1]
            pts = [str(p).strip() for p in q.get("points", []) if str(p).strip()]
            src = int(q.get("src", 0))
        except Exception:
            problems.append(f"Q{i}: wrong structure")
            continue
        if len(text) < 12 or len(text) > 170:
            problems.append(f"Q{i}: question length {len(text)}")
        elif len(opts) != 4 or len(set(o.lower() for o in opts)) != 4 or any(not o or len(o) > 80 for o in opts):
            problems.append(f"Q{i}: options must be 4 different short texts")
        elif ans not in "ABCD" or not ans:
            problems.append(f"Q{i}: answer '{ans}'")
        elif not re.search(r"[ऀ-ॿ]", text):
            problems.append(f"Q{i}: no Hindi in question")
        elif not 1 <= src <= nheads:
            problems.append(f"Q{i}: src {src} is not a real headline number")
        elif norm_title(text) in seen:
            problems.append(f"Q{i}: duplicate")
        else:
            seen.add(norm_title(text))
            good.append({"q": text, "options": opts, "answer": ans, "points": pts[:2], "_src": src})
    return good, problems


def answer_spread_ok(qs):
    """Reject a set where one letter is the answer for more than 45% of questions."""
    if len(qs) < 8:
        return True
    return max(sum(1 for q in qs if q["answer"] == c) for c in "ABCD") <= 0.45 * len(qs)


FAKE_HEADS = [("PIB (Hindi)", f"नमूना हेडलाइन {i}: सरकार ने योजना {i} की घोषणा की") for i in range(1, 17)]


def fake_response(n):
    qs = []
    for i in range(1, n + 1):
        qs.append({"q": f"नमूना प्रश्न {i}: योजना {i} की घोषणा किसने की?",
                   "options": ["केंद्र सरकार", "हरियाणा सरकार", "RBI", "नीति आयोग"],
                   "answer": "ABCD"[i % 4], "points": ["यह एक परीक्षण है", "असली खबर नहीं"], "src": (i % 16) + 1})
    for q in qs:   # make the correct option sit where "answer" says
        opts = ["केंद्र सरकार", "हरियाणा सरकार", "RBI", "नीति आयोग"]
        right = opts[0]
        opts.remove(right)
        opts.insert("ABCD".index(q["answer"]), right)
        q["options"] = opts
    return {"questions": qs}


# ----------------------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="YYYY-MM-DD, India date (default today)")
    ap.add_argument("--count", type=int, default=15)
    ap.add_argument("--key-slot", type=int, default=1)
    ap.add_argument("--out-dir", default="daily")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite today's file if it already exists")
    a = ap.parse_args()

    day = a.date or dt.datetime.now(IST).strftime("%Y-%m-%d")
    name = f"currentaffairs-{day}"
    path = os.path.join(a.out_dir, f"{name}.done.json")
    if os.path.exists(path) and not a.force and not a.dry_run:
        log(f"{path} already exists, nothing to do (use --force to redo)")
        return 0

    log("Collecting headlines ...")
    heads = FAKE_HEADS if a.fake else collect_headlines()
    log(f"{len(heads)} headlines in total")
    if len(heads) < max(12, a.count):
        log(f"::error::only {len(heads)} headlines found: not enough news to make {a.count} questions. Nothing was made.")
        return 2

    numbered = "\n".join(f"{i}. [{lab}] {t}" for i, (lab, t) in enumerate(heads, 1))
    prompt = PROMPT.format(n=a.count + 3, h=max(3, a.count // 4), heads=numbered)   # ask for a few extra, the checks drop bad ones
    if a.dry_run:
        print(prompt)
        return 0

    key_env = "GEMINI_API_KEY" + (f"_{a.key_slot}" if a.key_slot > 1 else "")
    key = os.environ.get(key_env, "")
    if not a.fake and not key:
        log(f"::error::{key_env} is not set (add it as a repository secret and pass it in the workflow)")
        return 2

    good = []
    for attempt in range(1, 4):
        log(f"Asking Gemini (try {attempt}/3) ...")
        data = fake_response(a.count + 3) if a.fake else gemini_json(prompt, key, MODELS)
        good, problems = clean_questions(data, len(heads))
        for p in problems:
            log("  dropped:", p)
        log(f"  {len(good)} valid questions")
        if len(good) >= a.count and answer_spread_ok(good[:a.count]):
            break
        if len(good) >= a.count:
            log("  answers are too lopsided (one letter for most questions), asking again")
        good = []
    if not good:
        log(f"::error::could not get {a.count} valid questions after 3 tries. Nothing was made.")
        return 3
    good = good[:a.count]

    d = dt.datetime.strptime(day, "%Y-%m-%d")
    months = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
    meta = dict(META)
    meta["title"] = f"करंट अफेयर्स {d.day} {months[d.month - 1]} {d.year} ({len(good)} प्रश्न)"
    questions = [{k: v for k, v in q.items() if not k.startswith("_")} for q in good]

    os.makedirs(a.out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "questions": questions}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out_dir, f"{name}.sources.txt"), "w", encoding="utf-8") as f:
        for i, q in enumerate(good, 1):
            lab, title = heads[q["_src"] - 1]
            f.write(f"Q{i}  ({q['answer']})  {q['q']}\n     from: [{lab}] {title}\n\n")
    log(f"Wrote {path} with {len(questions)} questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
