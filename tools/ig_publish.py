#!/usr/bin/env python3
"""Post one finished reel (a GitHub release made by video.yml) to Instagram.

Used by .github/workflows/post-reel.yml. Needs the repository secrets IG_ACCESS_TOKEN and IG_USER_ID.
Never prints the token.

    python tools/ig_publish.py --dry-run               # check token, pick the release, check the video link, post nothing
    python tools/ig_publish.py                         # post the oldest reel that was not posted yet
    python tools/ig_publish.py --tag video-12-xxx      # post this release
    python tools/ig_publish.py --refresh               # extend the token (used by refresh-ig-token.yml)

Which release is next: releases that have a "<name>-caption.txt" asset (only aspect=reel builds make one) and are not
listed in ig/posted.json, oldest first. After a successful post the release tag is added to ig/posted.json.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "https://graph.instagram.com"
VERSION = os.environ.get("IG_API_VERSION", "").strip().strip("/")
POSTED = Path("ig/posted.json")
RAW_TOKEN = os.environ.get("IG_ACCESS_TOKEN") or ""


def clean_token(t):
    """Pasted tokens often carry invisible junk: a newline, spaces, quotes, 'access_token=' or 'Bearer '."""
    t = re.sub(r"\s+", "", t)  # newlines/spaces anywhere (a phone copy can wrap the token)
    t = re.sub(r"^(?:access_token=|Bearer|OAuth)", "", t, flags=re.I)
    return t.strip("\"'`<>.,;")


TOKEN = clean_token(RAW_TOKEN)
IG_ID = re.sub(r"\D", "", os.environ.get("IG_USER_ID") or "")


def token_shape():
    """Safe description of the token (never the token itself) to find paste mistakes."""
    r = RAW_TOKEN
    return (f"length {len(r)} (after cleaning {len(TOKEN)}), starts with 'IG': {TOKEN[:2] == 'IG'}, "
            f"whitespace/newline inside: {bool(re.search(r'\s', r.strip()))}, quotes: {bool(re.search(r'[\"\'`]', r))}, "
            f"non-ASCII characters: {sum(ord(c) > 127 for c in r)}")


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def api(method, path, params=None):
    """Call the Instagram API. Returns parsed JSON; dies with the API's own error text (token never shown)."""
    url = f"{HOST}/{VERSION + '/' if VERSION else ''}{path}"
    data = None
    params = dict(params or {})
    params["access_token"] = TOKEN
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body).get("error", {})
            body = f"{err.get('message')} (code {err.get('code')}, subcode {err.get('error_subcode')})"
        except Exception:
            pass
        extra = f"\nToken as GitHub gave it to this run: {token_shape()}" if "code 190" in body else ""
        die(f"Instagram API {method} /{path} failed: HTTP {e.code}: {body.replace(TOKEN, '***') if TOKEN else body}{extra}")
    except Exception as e:
        die(f"Instagram API {method} /{path} failed: {e}")


def sh(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def load_posted():
    try:
        return json.loads(POSTED.read_text(encoding="utf-8"))
    except Exception:
        return []


def pick_release(tag):
    """Return (tag, video_asset, caption_asset)."""
    if tag:
        tags = [tag]
    else:
        rel = json.loads(sh("gh", "release", "list", "--limit", "100", "--json", "tagName,createdAt"))
        tags = [r["tagName"] for r in sorted(rel, key=lambda r: r["createdAt"])]
    posted = set(load_posted())
    for t in tags:
        if t in posted and not tag:
            continue
        try:
            assets = [a["name"] for a in json.loads(sh("gh", "release", "view", t, "--json", "assets"))["assets"]]
        except subprocess.CalledProcessError:
            if tag:
                die(f"release {t} not found")
            continue
        cap = next((a for a in assets if a.endswith("-caption.txt")), None)
        vid = next((a for a in assets if a.endswith(".mp4")), None)
        if cap and vid:
            return t, vid, cap
        if tag:
            die(f"release {t} has no reel caption (-caption.txt) - it was not built with aspect=reel")
    die("no unposted reel found (a reel build must have finished first)")


def check_video_url(url):
    """Follow redirects like Instagram will and make sure a video comes back."""
    req = urllib.request.Request(url, headers={"Range": "bytes=0-1023", "User-Agent": "facebookexternalhit/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ctype = r.headers.get("Content-Type", "")
            print(f"Video link answers {r.status}, content-type {ctype}, final host {urllib.parse.urlparse(r.geturl()).netloc}")
            if "video" not in ctype and "octet-stream" not in ctype:
                die(f"the video link does not return a video ({ctype}). Is the repository public?")
    except urllib.error.HTTPError as e:
        die(f"the video link returned HTTP {e.code}. The repository must be public so Instagram can fetch the file.")


def whoami():
    me = api("GET", "me", {"fields": "user_id,username"})
    uid = str(me.get("user_id") or me.get("id") or "")
    print(f"Token works: @{me.get('username')} (id {uid})")
    if IG_ID and uid and IG_ID != uid:
        print(f"WARNING: IG_USER_ID ({IG_ID}) differs from the token's account id ({uid}); using {uid}")
    return uid or IG_ID


def refresh():
    me = whoami()
    r = api("GET", "refresh_access_token", {"grant_type": "ig_refresh_token"})
    days = int(r.get("expires_in", 0)) // 86400
    print(f"Token refreshed: valid for about {days} more days for @{me}")
    new = r.get("access_token") or ""
    if new and new != TOKEN:
        Path("new_token.txt").write_text(new, encoding="utf-8")
        print("A NEW token string came back; the workflow will try to save it as the secret.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        die("secret IG_ACCESS_TOKEN is empty. Add it in GitHub: Settings > Secrets and variables > Actions.")
    if a.refresh:
        return refresh()
    uid = whoami()

    tag, vid, cap = pick_release(a.tag.strip())
    print(f"Release: {tag}\nVideo: {vid}")
    Path("reel").mkdir(exist_ok=True)
    sh("gh", "release", "download", tag, "--pattern", cap, "--dir", "reel", "--clobber")
    caption = Path("reel", cap).read_text(encoding="utf-8").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    url = f"https://github.com/{repo}/releases/download/{urllib.parse.quote(tag)}/{urllib.parse.quote(vid)}"
    check_video_url(url)
    print("---- caption ----\n" + caption + "\n-----------------")
    if a.dry_run:
        try:
            lim = api("GET", f"{uid}/content_publishing_limit", {"fields": "quota_usage,config"})
            print("Publishing limit info:", json.dumps(lim.get("data", lim), ensure_ascii=False))
        except SystemExit:
            print("(could not read the publishing limit, not a problem for a dry run)")
        print("DRY RUN OK: nothing was posted.")
        return

    c = api("POST", f"{uid}/media", {"media_type": "REELS", "video_url": url, "caption": caption, "share_to_feed": "true"})
    cid = c.get("id")
    if not cid:
        die(f"no container id came back: {c}")
    print(f"Container {cid} created, Instagram is fetching the video")
    status = ""
    for i in range(45):  # up to ~11 minutes
        time.sleep(15)
        s = api("GET", cid, {"fields": "status_code,status"})
        status = s.get("status_code", "")
        print(f"  [{(i + 1) * 15:>3}s] {status} {s.get('status', '')}")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            die(f"Instagram could not process the video: {s}. If it says it cannot download the file, the GitHub release link is not reachable for Instagram (tell Claude).")
    else:
        die("Instagram is still processing after 11 minutes. Nothing was published; run again.")

    p = api("POST", f"{uid}/media_publish", {"creation_id": cid})
    media_id = p.get("id")
    link = ""
    try:
        link = api("GET", media_id, {"fields": "permalink"}).get("permalink", "")
    except SystemExit:
        pass
    print(f"PUBLISHED reel {media_id} {link}")
    POSTED.parent.mkdir(exist_ok=True)
    posted = load_posted()
    posted.append(tag)
    POSTED.write_text(json.dumps(posted, indent=1), encoding="utf-8")
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"Posted **{tag}** to Instagram: {link}\n")


if __name__ == "__main__":
    main()
