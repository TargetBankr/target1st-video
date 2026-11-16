"""Offline test for the Gemini voice-text rewrite (gemini_say) in build.py. No API key, no quota.
Usage: python tools/test_gemini_say.py      (exits with an error if any case is wrong)"""
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("b", pathlib.Path(__file__).resolve().parent.parent / "build.py")
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
say = lambda t, m=None: b.gemini_say(b.spoken(t, {}), m or {})
CASES = {
    "<tr>": "T R tag", "<table>": "table tag", "<html>": "H T M L tag", "</td>": "closing T D tag",
    "He plays ___ guitar.": "He plays blank guitar.",
    "255 = 15 x 16 + 15 = FF": "255 equals 15 times 16 plus 15 equals F F",
    "2x2x3 = 12": "2 times 2 times 3 equals 12",
    "3x + 7 = 25": "3 x plus 7 equals 25",
    "150 x 100 / 75 = 200": "150 times 100 by 75 equals 200",
    "The ratio is 5:3.": "The ratio is 5 to 3.",
    "Ctrl + F4": "Ctrl plus F 4", "F10": "F 10", "1F": "1 F", "EE": "E E",
    "FF का binary रूप 11111111 होता है": "F F का binary रूप 1 1 1 1 1 1 1 1 होता है",
    "1000000": "1000000", "10000000": "10000000", "10:30 बजे": "10:30 बजे",
    "B) 54 km/h": "B, 54 किलोमीटर प्रति घंटा",
    "has/have + been + V3": "has or have plus been plus V 3",
    "SP = MP - Discount = 500 - 50 = Rs 450": "SP बराबर MP घटा Discount बराबर 500 घटा 50 बराबर 450 रुपये",
    "1 EB = 1024 PB": "1 E B equals 1024 P B", "पुराना format .ppt था": "पुराना format ppt था",
    "He said that he was busy.": "He said that he was busy.", "2nd and 3rd": "2nd and 3rd",
}
bad = [(k, say(k), v) for k, v in CASES.items() if say(k) != v]
for k, got, want in bad:
    print(f"WRONG {k!r}\n   got  {got!r}\n   want {want!r}")
assert say("A = 1", {"gemini_symbols": False}) == "A = 1"
assert say("OMR", {"gemini_say_map": {"OMR": "ओ एम आर"}}) == "ओ एम आर"
sys.exit(1 if bad else print(f"ok: {len(CASES) + 2} cases") or 0)
