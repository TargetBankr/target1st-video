#!/usr/bin/env python3
"""Post one finished reel (a GitHub release made by video.yml) to Instagram.

Used by .github/workflows/post-reel.yml. Needs the repository secrets IG_ACCESS_TOKEN and IG_USER_ID.
Never prints the token.

    python tools/ig_publish.py --dry-run               # check token, pick the release, check the video link, post nothing
    python tools/ig_publish.py                         # post the oldest reel that was not posted yet
    python tools/ig_publish.py --tag video-12-xxx      # post this release
    python tools/ig_publish.py --refresh               # extend the token (used by refresh-ig-token.yml)

Stories: a release whose tag contains "-story" (made by tools/make_reels.py --stories) is posted as an Instagram STORY
(video only: the API cannot add link stickers, the QR codes are in the video). Reels and stories never pick each other's releases.

    python tools/ig_publish.py --kind story            # post the oldest story that was not posted yet
    python tools/ig_publish.py                         # (--kind reel is the default) oldest reel

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

VERSION = os.environ.get("IG_API_VERSION", "").strip().strip("/")
POSTED = Path("ig/posted.json")
RAW_TOKEN = os.environ.get("IG_ACCESS_TOKEN") or ""


def clean_token(t):
    """Pasted tokens often carry invisible junk: a newline, spaces, quotes, 'access_token=' or 'Bearer '."""
    t = re.sub(r"\s+", "", t)  # newlines/spaces anywhere (a phone copy can wrap the token)
    t = re.sub(r"^(?:access_token=|Bearer|OAuth)", "", t, flags=re.I)
    return t.strip("\"'`<>.,;")


TOKEN = clean_token(RAW_TOKEN)
# Two kinds of token exist. "IG..." = Instagram Login token -> graph.instagram.com.
# "EA..." (EAAG, EAAx, EAG...) = Facebook Login token (the Instagram account is linked to a Facebook Page) -> graph.facebook.com.
FB_LOGIN = bool(TOKEN) and not TOKEN.startswith("IG")
HOST = (os.environ.get("IG_HOST", "").strip().rstrip("/")
        or ("https://graph.facebook.com" if FB_LOGIN else "https://graph.instagram.com"))
IG_ID = re.sub(r"\D", "", os.environ.get("IG_USER_ID") or "")


def token_shape():
    """Safe description of the token (never the token itself) to find paste mistakes."""
    r = RAW_TOKEN
    return (f"length {len(r)} (after cleaning {len(TOKEN)}), starts with: {TOKEN[:4]}, "
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


def is_story(tag):
    return "-story" in tag


def pick_release(tag, kind="reel"):
    """Return (tag, video_asset, caption_asset). kind = reel | story decides which releases are considered (unless a tag is given)."""
    if tag:
        tags = [tag]
    else:
        rel = json.loads(sh("gh", "release", "list", "--limit", "100", "--json", "tagName,createdAt"))
        tags = [r["tagName"] for r in sorted(rel, key=lambda r: r["createdAt"])]
    posted = set(load_posted())
    for t in tags:
        if t in posted and not tag:
            continue
        if not tag and is_story(t) != (kind == "story"):
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
    die(f"no unposted {kind} found (a {kind} build must have finished first)")


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
    if FB_LOGIN:
        if not IG_ID:
            die("secret IG_USER_ID is empty. For a Facebook-login token it must be the Instagram account ID.")
        me = api("GET", IG_ID, {"fields": "username"})
        print(f"Token works (Facebook login): @{me.get('username')} (id {IG_ID})")
        return IG_ID
    me = api("GET", "me", {"fields": "user_id,username"})
    uid = str(me.get("user_id") or me.get("id") or "")
    print(f"Token works: @{me.get('username')} (id {uid})")
    if IG_ID and uid and IG_ID != uid:
        print(f"WARNING: IG_USER_ID ({IG_ID}) differs from the token's account id ({uid}); using {uid}")
    return uid or IG_ID


def refresh():
    me = whoami()
    if FB_LOGIN:
        app_id = re.sub(r"\s+", "", os.environ.get("FB_APP_ID") or "")
        secret = re.sub(r"\s+", "", os.environ.get("FB_APP_SECRET") or "")
        if not (app_id and secret):
            die("this is a Facebook-login token (EA...). To extend it automatically, add the repository secrets FB_APP_ID and "
                "FB_APP_SECRET (Meta dashboard > App settings > Basic). Until then check its expiry at "
                "developers.facebook.com/tools/debug/accesstoken and paste a new token before it ends.")
        url = f"{HOST}/{VERSION + '/' if VERSION else ''}oauth/access_token?" + urllib.parse.urlencode(
            {"grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret, "fb_exchange_token": TOKEN})
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                res = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            die(f"token exchange failed: HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        days = int(res.get("expires_in", 0)) // 86400
        print(f"Token extended: about {days} more days for @{me}" if days else f"Token exchanged for @{me} (no expiry given)")
        new = res.get("access_token") or ""
    else:
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
    ap.add_argument("--kind", default="reel", choices=["reel", "story"], help="which releases to pick when no --tag is given")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--if-empty-ok", action="store_true", help="nothing to post is not an error (scheduled runs)")
    a = ap.parse_args()
    if not TOKEN:
        die("secret IG_ACCESS_TOKEN is empty. Add it in GitHub: Settings > Secrets and variables > Actions.")
    if a.refresh:
        return refresh()
    uid = whoami()

    try:
        tag, vid, cap = pick_release(a.tag.strip(), a.kind)
    except SystemExit as e:
        if a.if_empty_ok and not a.tag.strip():
            print("Nothing to post right now.")
            return
        raise
    print(f"Release: {tag}\nVideo: {vid}")
    Path("reel").mkdir(exist_ok=True)
    sh("gh", "release", "download", tag, "--pattern", cap, "--dir", "reel", "--clobber")
    caption = Path("reel", cap).read_text(encoding="utf-8").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    url = f"https://github.com/{repo}/releases/download/{urllib.parse.quote(tag)}/{urllib.parse.quote(vid)}"
    check_video_url(url)
    if is_story(tag):
        print("This is a STORY: posted as video only (no caption, no link sticker; the QR codes are in the video).")
    else:
        print("---- caption ----\n" + caption + "\n-----------------")
    if a.dry_run:
        try:
            lim = api("GET", f"{uid}/content_publishing_limit", {"fields": "quota_usage,config"})
            print("Publishing limit info:", json.dumps(lim.get("data", lim), ensure_ascii=False))
        except SystemExit:
            print("(could not read the publishing limit, not a problem for a dry run)")
        print("DRY RUN OK: nothing was posted.")
        return

    story = is_story(tag)
    if story:
        c = api("POST", f"{uid}/media", {"media_type": "STORIES", "video_url": url})
    else:
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
    print(f"PUBLISHED {'story' if story else 'reel'} {media_id} {link}")
    POSTED.parent.mkdir(exist_ok=True)
    posted = load_posted()
    posted.append(tag)
    POSTED.write_text(json.dumps(posted, indent=1), encoding="utf-8")
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"Posted **{tag}** to Instagram ({'story' if story else 'reel'}): {link}\n")


if __name__ == "__main__":
    main()
