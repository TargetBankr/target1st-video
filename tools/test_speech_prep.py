"""Offline tests for `||` parsing and the Gemini speech-prep pass (text model is mocked)."""
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build as b

data = {"meta": {"pronounce": {}, "speech_prep": True}, "questions": [
    {"q": "Which is 5x faster? || कौन सा पाँच गुना तेज़ है?", "options": ["A + B = 7 || ए प्लस बी बराबर सात", "FF", "<tr> tag", "none"],
     "answer": "A", "points": ["Plain point 2+2=4", "Long shown || " + "spoken " * 60, {"show": "x", "say": "dict say"}],
     "trick": "T || ट्रिक बोल"}]}
qs, steps = b.make_steps(data, 0, "quiz")
q = qs[0]
assert q["q"] == "Which is 5x faster?" and q["options"][0] == "A + B = 7", q
txt = {s["say"] for s in steps if "say" in s}
assert any("कौन सा पाँच गुना तेज़ है?" in t for t in txt)
assert not any("||" in t or b.SAY0 in t for t in txt)
# hand text is protected from rules
m = next(s for s in steps if "ए प्लस बी" in s.get("say", ""))
v = b.gemini_say(m["say"], data["meta"], m["say_m"])
assert "ए प्लस बी बराबर सात" in v and "FF" not in v and "F F" in v, v
# long spoken part is not cut
lp = next(s for s in steps if "spoken spoken" in s.get("say", ""))
assert len(lp["say"]) > 300
# prep with mocked model
seen = []
def fake(prompt, model, key):
    seen.append(model)
    if model == "bad":
        raise RuntimeError("404")
    ids = json.loads(prompt[prompt.index("{\n") if "{\n" in prompt else prompt.rindex("\n\n{") + 2:])
    return {k: v.replace("2+2=4", "दो प्लस दो बराबर चार") for k, v in ids.items()}
with tempfile.TemporaryDirectory() as d:
    w = Path(d); (w / "audio").mkdir()
    meta = dict(data["meta"], speech_prep_models=["bad", "ok"])
    b.speech_prep(steps, meta, w, "k", call=fake)
    p = next(s for s in steps if "2+2=4" in s.get("say", ""))
    assert "दो प्लस दो बराबर चार" in p["prep"], p.get("prep")
    h = next(s for s in steps if "ए प्लस बी" in s.get("say", ""))
    assert b.SAY0 in h["prep"], h["prep"]          # hand part restored
    n = len(seen)
    for s in steps: s.pop("prep", None)
    b.speech_prep(steps, meta, w, "k", call=lambda *a: (_ for _ in ()).throw(RuntimeError("must use cache")))
    assert next(s for s in steps if "2+2=4" in s.get("say", "")).get("prep")
    # bad answers rejected
    for s in steps: s.pop("prep", None)
    (w / "audio" / "_prep_cache.json").unlink()
    b.speech_prep(steps, meta, w, "k", call=lambda pr, m, k: {"0": "{junk}"})
    assert not any(s.get("prep") for s in steps)
print("speech prep tests OK")
