#!/usr/bin/env python3
"""Make the 50-question video JSONs for the HSSC Group D + SSC series (series/plan.json) with Gemini.

    plan row  ->  Gemini writes MCQs in small batches  ->  checks + duplicate filter  ->  series/ready/<id>.json

Day N = gdNN (HSSC Group D) + sscNN (SSC).  Files written per set (none of them is a ".done" file, so nothing builds by itself):
    series/ready/<id>.json        the video JSON (same format as sscmock01-gemini.done.json)
    series/ready/<id>.title.txt   YouTube title + description (no tags)
    series/ready/<id>.check.txt   every question with the source its answer was checked against, for your 2-minute scan

    python tools/make_series.py --days 1-3                 # gd01..gd03 + ssc01..ssc03
    python tools/make_series.py --ids gd05,ssc05 --force   # redo these sets
    python tools/make_series.py --days 1 --dry-run         # print the first prompt, call nothing
    python tools/make_series.py --days 1-2 --fake          # no network: made-up questions, to test the checks and files

Needs repository secrets GEMINI_API_KEY, GEMINI_API_KEY_2 ... _5 (any that exist are used; if one is out of quota the next is tried).
Standard library only. Duplicates: a question too similar to any question already in the repo (other JSON files) or earlier in
the same set is dropped and replaced, so no video repeats another one.
"""
import argparse
import glob
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_daily_ca import MODELS, norm_title  # noqa: E402  (same text-model list as the daily current-affairs bot)

HI = re.compile(r"[ऀ-ॿ]")
# options that point at other options ("A और B दोनों", "उपरोक्त सभी"): never move these around
LOCK = re.compile(r"दोनों|उपरोक्त|सभी|इनमें से|कोई नहीं|\b[ABCD]\s*(?:और|तथा|,)|केवल\s*[ABCD]")

PROMPT = """तुम Target1st यूट्यूब चैनल के लिए {exam_line} के मौलिक (ORIGINAL) बहुविकल्पीय प्रश्न बनाने वाले विशेषज्ञ हो।

विषय: {topic}
इन उप-विषयों पर लगभग बराबर प्रश्न बनाओ:
{subs}

{n} प्रश्न बनाओ। सख्त नियम:
1. भाषा सरल हिंदी (देवनागरी)। ICJ, GDP, UPSC जैसे संक्षेप अंग्रेज़ी में रहने दो।
2. सिर्फ़ ऐसे तथ्य पूछो जो मानक पुस्तकों और सरकारी स्रोतों में स्थापित हैं और बदलते नहीं। जिस तथ्य पर 100% भरोसा न हो, उस पर प्रश्न मत बनाओ। तेज़ी से बदलने वाले तथ्य (वर्तमान मंत्री, मुख्यमंत्री, ताज़ा आँकड़े) मत पूछो, अगर पूछो तो साल लिखो।
3. {haryana_rule}
4. प्रश्न एक वाक्य, 150 अक्षर से कम। चार अलग-अलग छोटे विकल्प (हर एक 50 अक्षर से कम)। "उपरोक्त सभी", "इनमें से कोई नहीं", "A और B दोनों" जैसे विकल्प मत रखो। गलत विकल्प असली और भ्रमित करने वाले हों।
5. "answer" सिर्फ़ A, B, C या D।
6. "points": ठीक 3 छोटे बिंदु (हर बिंदु 100 अक्षर से कम)। पहला बिंदु: उत्तर सही क्यों है। दूसरा और तीसरा: उसी विषय के दो और परीक्षा-उपयोगी तथ्य जो प्रश्न के उत्तर में पहले से न आए हों।
7. "trick": एक छोटी याद रखने की ट्रिक या शॉर्टकट (100 अक्षर से कम)।
8. "conf": "high" अगर तुम्हें तथ्य पर पूरा भरोसा है, "medium" अगर थोड़ा भी संदेह है।
9. कठिनाई: 40% आसान, 40% मध्यम, 20% कठिन। एक ही तथ्य दो बार मत पूछो। शब्द अपने हों, किसी किताब, वेबसाइट, यूट्यूब चैनल या पिछले पेपर से कॉपी नहीं।
10. कठिन-से-पढ़ने वाले चिह्न "स्क्रीन पर || बोलने में" रूप में लिखो।
{avoid}
सिर्फ़ यह JSON लौटाओ, और कुछ नहीं:
{{"questions": [{{"q": "...", "options": ["...", "...", "...", "..."], "answer": "A", "points": ["...", "...", "..."], "trick": "...", "conf": "high"}}]}}
"""


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------------------------------------- Gemini

def get_keys():
    keys = []
    for slot in range(1, 6):
        env = "GEMINI_API_KEY" + (f"_{slot}" if slot > 1 else "")
        if os.environ.get(env, "").strip():
            keys.append((slot, os.environ[env].strip()))
    return keys


class QuotaOut(RuntimeError):
    """Every key/model answered with its DAILY limit: waiting minutes will not help, only the next quota day."""


def ask_gemini(prompt, keys, first_slot, grounded=False):
    """Try every key (starting at first_slot) with every model. Returns the parsed dict.
    grounded=True lets the model search Google (used by the checking pass; the API does not allow JSON mode together with search,
    so the JSON is cut out of the text instead).
    Busy / per-minute limits: waits longer each round (1, 2, 4 min) instead of giving up the whole set.
    Every key/model out for the DAY: raises QuotaOut at once (main() then stops instead of failing set after set)."""
    order = sorted(keys, key=lambda k: (k[0] - first_slot) % 6)
    last = "no key"
    waits = [60, 120, 240]
    for rnd in range(len(waits) + 1):
        tries = day_out = 0
        for slot, key in order:
            for model in MODELS:
                cfg = {"temperature": 0.1 if grounded else 0.5, "maxOutputTokens": 32768}
                if not grounded:
                    cfg["responseMimeType"] = "application/json"
                payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg}
                if grounded:
                    payload["tools"] = [{"google_search": {}}]
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
                tries += 1
                try:
                    with urllib.request.urlopen(req, timeout=300) as r:
                        resp = json.loads(r.read().decode("utf-8"))
                    text = "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"])
                    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                    if grounded:
                        text = text[text.index("{"):text.rindex("}") + 1]
                    return json.loads(text)
                except urllib.error.HTTPError as e:
                    msg = e.read().decode("utf-8", "ignore")
                    if e.code == 429 and re.search(r"per\s*day", msg, re.I):
                        day_out += 1
                        last = f"key {slot} {model}: HTTP 429 daily limit"
                    else:
                        last = f"key {slot} {model}: HTTP {e.code}"
                except Exception as e:
                    last = f"key {slot} {model}: {type(e).__name__}: {e}"
                log(f"  failed: {last}")
        if tries and day_out == tries:
            raise QuotaOut(f"every Gemini key/model is out of its daily limit ({last})")
        if rnd < len(waits):
            log(f"  every key/model failed, waiting {waits[rnd]} s and trying again ({rnd + 1}/{len(waits)})")
            time.sleep(waits[rnd])
    raise RuntimeError(f"no Gemini key/model answered ({last})")


# ----------------------------------------------------------------------------------------------- checking pass

VERIFY_PROMPT = """तुम एक सख्त तथ्य-जाँचकर्ता हो। नीचे परीक्षा के बहुविकल्पीय प्रश्न हैं, हर एक के साथ बताया गया सही उत्तर है।
Google Search से भरोसेमंद स्रोत (सरकारी साइट, NCERT, मानक पुस्तकें, विश्वसनीय समाचार, विश्वकोश) देखकर हर प्रश्न जाँचो।

हर प्रश्न के लिए "verdict" इनमें से एक दो:
- "ok": तुम्हें किसी भरोसेमंद स्रोत में पुष्टि मिली कि बताया गया उत्तर सही है और बाकी तीन विकल्प गलत हैं।
- "wrong": बताया गया उत्तर गलत है (अगर सही विकल्प दिखे तो "correct" में उसका अक्षर लिखो)।
- "ambiguous": एक से ज़्यादा विकल्प सही हो सकते हैं, या प्रश्न अधूरा/उलझा हुआ है।
- "unsure": पुष्टि नहीं मिली, या स्रोत आपस में अलग-अलग बताते हैं।
- "dup": इसी सूची के किसी और प्रश्न जैसा ही तथ्य पूछ रहा है ("dup_of" में उस प्रश्न का नंबर)।
सिर्फ़ पक्की पुष्टि पर "ok" दो। अंदाज़े से "ok" मत दो।

सिर्फ़ यह JSON लौटाओ:
{{"results": [{{"n": 1, "verdict": "ok", "src": "स्रोत का छोटा नाम", "correct": "A", "dup_of": null}}]}}

प्रश्न:
{items}
"""


def verify_batch(batch, keys, first_slot, fake=False):
    """batch: list of question dicts. Returns the dicts that were confirmed (with q['_src'] set); the rest are dropped."""
    if fake:
        rng = random.Random(batch[0]["q"])
        kept = [q for q in batch if rng.random() > 0.2]
        for q in kept:
            q["_src"] = "नमूना"
        return kept, len(batch) - len(kept)
    items = "\n".join(
        f"{i}. {q['q']}  A) {q['options'][0]}  B) {q['options'][1]}  C) {q['options'][2]}  D) {q['options'][3]}  -> बताया गया उत्तर: {q['answer']}"
        for i, q in enumerate(batch, 1))
    data = ask_gemini(VERIFY_PROMPT.format(items=items), keys, first_slot, grounded=True)
    verdicts = {}
    for r in data.get("results", []):
        try:
            verdicts[int(r["n"])] = r
        except Exception:
            continue
    kept = []
    for i, q in enumerate(batch, 1):
        r = verdicts.get(i)
        if r and str(r.get("verdict", "")).lower() == "ok":
            q["_src"] = str(r.get("src") or "")[:60]
            kept.append(q)
    return kept, len(batch) - len(kept)


# ----------------------------------------------------------------------------------------------- checks

def toks(s):
    return set(norm_title(s).split())


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def load_bank(skip_id=""):
    """Every question already in the repo's JSON files: [(token set, right answer text)]."""
    bank = []
    paths = glob.glob("*.json") + glob.glob("daily/*.json") + glob.glob("series/ready/*.json")
    for p in paths:
        if skip_id and os.path.basename(p) == f"{skip_id}.json":
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
            for q in d.get("questions", []):
                right = q["options"]["ABCD".index(q["answer"])] if q.get("options") and q.get("answer") in "ABCD" else ""
                bank.append((toks(q.get("q", "")), norm_title(right)))
        except Exception:
            continue
    return bank


def is_duplicate(q, bank):
    t, right = toks(q["q"]), norm_title(q["options"]["ABCD".index(q["answer"])])
    for bt, bright in bank:
        j = jaccard(t, bt)
        if j >= 0.7 or (j >= 0.45 and right and right == bright):
            return True
    return False


def clean(data):
    """(good, problems). Anything not fully valid is dropped, never repaired by guessing."""
    good, problems = [], []
    for i, q in enumerate(data.get("questions", []) if isinstance(data, dict) else [], 1):
        try:
            text = str(q["q"]).strip()
            opts = [str(o).strip() for o in q["options"]]
            ans = str(q["answer"]).strip().upper()[:1]
            pts = [str(p).strip() for p in q.get("points", []) if str(p).strip()]
            trick = str(q.get("trick") or "").strip()
            conf = str(q.get("conf") or "high").strip().lower()
        except Exception:
            problems.append(f"Q{i}: wrong structure")
            continue
        pts = [p for p in pts if len(p) <= 110][:4]
        if len(text) < 12 or len(text) > 170:
            problems.append(f"Q{i}: question length {len(text)}")
        elif len(opts) != 4 or len({o.lower() for o in opts}) != 4 or any(not o or len(o) > 80 for o in opts):
            problems.append(f"Q{i}: options must be 4 different short texts")
        elif not ans or ans not in "ABCD":
            problems.append(f"Q{i}: answer {ans!r}")
        elif not HI.search(text):
            problems.append(f"Q{i}: no Hindi in the question")
        elif len(pts) < 2:
            problems.append(f"Q{i}: fewer than 2 usable points")
        else:
            good.append({"q": text, "options": opts, "answer": ans, "points": pts,
                         "trick": trick if 0 < len(trick) <= 110 else "", "_conf": "medium" if conf.startswith("med") else "high"})
    return good, problems


def balance_answers(qs, rng):
    """Spread the right answers evenly over A-D by moving the right option (questions with 'A और B' style options stay)."""
    free = [q for q in qs if not any(LOCK.search(o) for o in q["options"])]
    pool = list("ABCD") * (len(free) // 4) + rng.sample("ABCD", len(free) % 4)
    rng.shuffle(pool)
    for q, target in zip(free, pool):
        i, t = "ABCD".index(q["answer"]), "ABCD".index(target)
        if i != t:
            q["options"][i], q["options"][t] = q["options"][t], q["options"][i]
            q["answer"] = target
    return qs


# ----------------------------------------------------------------------------------------------- fake mode

def fake_questions(n, seed):
    rng = random.Random(seed)
    def word():
        return "".join(chr(0x0915 + rng.randrange(30)) for _ in range(rng.randint(4, 7)))
    out = []
    for _ in range(n):
        out.append({"q": "नमूना " + " ".join(word() for _ in range(7)) + " क्या है?",
                    "options": [word() for _ in range(4)], "answer": rng.choice("ABCD"),
                    "points": [" ".join(word() for _ in range(4)) for _ in range(3)], "trick": word(),
                    "conf": rng.choice(["high", "high", "high", "medium"])})
    return {"questions": out}


# ----------------------------------------------------------------------------------------------- one set

def build_prompt(plan, row, n, have):
    ex = plan["exams"][row["exam"]]
    avoid = ""
    if have:
        stems = "\n".join("- " + q["q"][:45] for q in have[-70:])
        avoid = "\nइन प्रश्नों के विषय पहले बन चुके हैं, इन्हें और इनसे मिलते-जुलते तथ्यों को दोबारा मत पूछो:\n" + stems + "\n"
    hr = ("लगभग सभी प्रश्न हरियाणा से जुड़े हों।" if ex.get("haryana") and not row["topic"].startswith("HSSC Group D फुल")
          and "हरियाणा" in row["topic"] else "प्रश्न परीक्षा-स्तर के और विषय के अनुरूप हों।")
    if row["topic"].startswith("HSSC Group D फुल"):
        hr = "लगभग आधे प्रश्न हरियाणा GK से हों, बाकी भारत GK से।"
    return PROMPT.format(exam_line=ex["exam_line"], topic=row["topic"],
                         subs="\n".join("- " + s for s in row["subtopics"]), n=n, haryana_rule=hr, avoid=avoid)


def make_set(plan, row, keys, args, base_meta):
    ex = plan["exams"][row["exam"]]
    want = int(plan.get("count", 50))
    day = int(row["day"])
    log(f"== {row['id']}  (day {day})  {row['topic']}")
    bank = load_bank(skip_id=row["id"])
    have = []
    first_slot = ((day - 1) % 4) + 1 if row["exam"] == "gd" else ((day + 1) % 4) + 1
    dropped_total = 0
    for rnd in range(1, 13):
        n = min(25, int((want - len(have)) * 1.5) + 6)
        prompt = build_prompt(plan, row, n, have)
        if args.dry_run:
            print(prompt)
            return None
        log(f"  round {rnd}: asking for {n} (have {len(have)}/{want})")
        data = fake_questions(n, f"{row['id']}-{rnd}") if args.fake else ask_gemini(prompt, keys, first_slot)
        good, problems = clean(data)
        fresh, dropped_dup = [], 0
        for q in good:
            if len(have) + len(fresh) >= want + 10:
                break
            if is_duplicate(q, bank) or is_duplicate(q, [(toks(h["q"]), norm_title(h["options"]["ABCD".index(h["answer"])])) for h in have + fresh]):
                dropped_dup += 1
                continue
            fresh.append(q)
        for p in problems[:6]:
            log("   dropped:", p)
        log(f"  +{len(good)} valid, {dropped_dup} duplicates dropped, {len(fresh)} go to the fact check")
        step = max(1, -(-len(fresh) // max(1, -(-len(fresh) // 13))))   # even chunks of at most 13: 25 -> 13 + 12, never a lone question
        for i in range(0, len(fresh), step):
            if len(have) >= want:
                break
            chunk = fresh[i:i + step]
            if args.no_verify:
                for q in chunk:
                    q["_src"] = ""
                kept, bad = chunk, 0
            else:
                kept, bad = verify_batch(chunk, keys, first_slot, fake=args.fake)
                if not args.fake:
                    time.sleep(6)
            have.extend(kept[:want - len(have)])
            dropped_total += bad
            log(f"   fact check: {len(kept)} confirmed, {bad} dropped (total {len(have)}/{want})")
        if len(have) >= want:
            break
        if not args.fake:
            time.sleep(8)
    log(f"  fact check dropped {dropped_total} question(s) for this set")
    if len(have) < int(want * 0.9):  # 45 of 50
        log(f"::error::{row['id']}: only {len(have)} usable questions out of {want}. Nothing was written for this set.")
        return None
    have = balance_answers(have[:want], random.Random(row["id"]))

    num = ex["number_start"] + day - 1
    title = ex["title"].format(num=num, n=len(have), topic=row["topic"])
    meta = dict(base_meta)
    meta.pop("title", None)
    slot = first_slot
    meta.update({
        "title": title, "subtitle": ex["subtitle"], "format": ex["format"],
        "theme": plan["themes"][(day - 1 + (0 if row["exam"] == "gd" else 1)) % len(plan["themes"])],
        "layout": plan["layouts"][(day - 1 + (0 if row["exam"] == "gd" else 1)) % len(plan["layouts"])],
        "key_slot": slot, "speech_prep_key_slot": slot,
    })
    questions = []
    for q in have:
        item = {"q": q["q"], "options": q["options"], "answer": q["answer"], "points": q["points"]}
        if q["trick"]:
            item["trick"] = q["trick"]
        questions.append(item)

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"{row['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "questions": questions}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out_dir, f"{row['id']}.title.txt"), "w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        f.write(f"{ex['subtitle']} की तैयारी के लिए {len(have)} महत्वपूर्ण प्रश्न | विषय: {row['topic']}\n\n")
        f.write("इस वीडियो में:\n" + "\n".join("• " + s for s in row["subtopics"]) + "\n\n")
        f.write("हर प्रश्न का उत्तर, 3 जरूरी तथ्य और याद रखने की ट्रिक। वीडियो को सेव करें और रिवीज़न के लिए दोबारा देखें।\n")
    with open(os.path.join(args.out_dir, f"{row['id']}.check.txt"), "w", encoding="utf-8") as f:
        f.write(f"{row['id']} {title}\n{len(have)} प्रश्न {'बिना जाँच के' if args.no_verify else 'Google Search से जाँचे गए'}; {dropped_total} प्रश्न जाँच में हटाए गए।\n"
                "नीचे हर प्रश्न, उत्तर और जाँच का स्रोत है। 2 मिनट में नज़र मार लो।\n\n")
        for i, q in enumerate(have, 1):
            f.write(f"Q{i}  {q['q']}\n     उत्तर ({q['answer']}): {q['options']['ABCD'.index(q['answer'])]}   [{q.get('_src', '')}]\n\n")
    med = []
    log(f"  wrote {path}  ({len(questions)} questions, fact-checked)")
    return path


# ----------------------------------------------------------------------------------------------- main

def parse_days(spec):
    out = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            out += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.append(int(part))
        else:
            raise SystemExit(f"cannot read days {part!r}: use 1-6 or 3,5,8")
    return out


def load_base_meta(name, out_dir):
    """The meta (voice, models, fillers...) every new set starts from. Looks for plan.json's base_meta as typed, then for the
    same file name in any folder, and as a last resort copies the meta of an already made set in series/ready/."""
    tried = []
    if name:
        tried.append(name)
        if os.path.isfile(name):
            return json.load(open(name, encoding="utf-8"))["meta"]
        found = sorted(glob.glob(f"**/{os.path.basename(name)}", recursive=True))
        if found:
            log(f"base_meta {name} found at {found[0]}")
            return json.load(open(found[0], encoding="utf-8"))["meta"]
    ready = sorted(glob.glob(os.path.join(out_dir, "*.json")) + glob.glob(os.path.join("series", "ready", "*.json")),
                   key=os.path.getmtime, reverse=True)
    if ready:
        log(f"::warning::base_meta {name or '(not set)'} is not in the repo; using the settings of {ready[0]} instead "
            "(put the file back or fix base_meta in series/plan.json)")
        return json.load(open(ready[0], encoding="utf-8"))["meta"]
    raise SystemExit(f"base_meta not found ({', '.join(tried) or 'not set in plan.json'}) and no made set to copy settings from")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="series/plan.json")
    ap.add_argument("--days", default="", help="e.g. 1-6 or 3,5: makes gdNN and sscNN for those days")
    ap.add_argument("--ids", default="", help="e.g. gd05,ssc05")
    ap.add_argument("--out-dir", default="series/ready")
    ap.add_argument("--force", action="store_true", help="redo sets whose file already exists")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="skip the Google-Search fact check (not recommended)")
    ap.add_argument("--made-list", default="", help="write the paths made (in upload order) to this file")
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding="utf-8"))
    rows = {r["id"]: r for r in plan["sets"]}
    if args.ids:
        wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
    elif args.days:
        wanted = [f"{e}{d:02d}" for d in parse_days(args.days) for e in ("gd", "ssc")]
    else:
        raise SystemExit("give --days 1-3 or --ids gd01,ssc01")
    bad = [w for w in wanted if w not in rows]
    if bad:
        raise SystemExit(f"not in the plan: {', '.join(bad)}")

    base_meta = load_base_meta(plan.get("base_meta", ""), args.out_dir)
    keys = get_keys()
    if not keys and not args.fake and not args.dry_run:
        log("::error::no GEMINI_API_KEY secret is set in this run")
        return 2
    log(f"{len(keys)} Gemini key(s) available: slots {[k[0] for k in keys]}")

    made, failed = [], []
    for sid in wanted:
        path = os.path.join(args.out_dir, f"{sid}.json")
        if os.path.exists(path) and not args.force and not args.dry_run:
            log(f"== {sid}: {path} already exists, skipped (use --force to redo)")
            continue
        try:
            p = make_set(plan, rows[sid], keys, args, base_meta)
        except QuotaOut as e:
            # every key is out for the day: the next sets would fail the same way, so stop here (they stay to do)
            left = wanted[wanted.index(sid):]
            log(f"::warning::{sid}: {e}. Stopping here; not made yet: {', '.join(left)}. Run again after about 1:30 pm IST.")
            failed.extend(left)
            break
        except Exception as e:   # e.g. the fact check could not run: never write unchecked questions, go on with the next set
            log(f"::error::{sid} failed: {type(e).__name__}: {e}")
            p = None
        if args.dry_run:
            return 0
        (made if p else failed).append(p or sid)
    if args.made_list:
        with open(args.made_list, "w") as f:
            f.write("\n".join(made) + ("\n" if made else ""))
    log(f"made {len(made)} set(s), failed {len(failed)}" + (f": {', '.join(failed)}" if failed else ""))
    return 1 if failed and not made else 0


if __name__ == "__main__":
    sys.exit(main())
