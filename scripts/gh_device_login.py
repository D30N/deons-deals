#!/usr/bin/env python3
"""GitHub OAuth device flow (same flow `gh auth login` uses).
Prints the user code for the human, polls until approved, then stores the
token in gh's config. NEVER prints the token itself."""
import json, os, sys, time, urllib.request

CLIENT_ID = "178c6fc778ccc68e1d6a"  # GitHub CLI's public OAuth app id
SCOPE = "repo"

def post(url, data):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(),
        headers={"Accept": "application/json", "User-Agent": "deons-deals-setup"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

import urllib.parse

print("STEP 1: requesting device code...", flush=True)
dc = post("https://github.com/login/device/code",
         {"client_id": CLIENT_ID, "scope": SCOPE})
print("USER_CODE=" + dc["user_code"], flush=True)
print("VERIFY_URL=" + dc.get("verification_uri", "https://github.com/login/device"), flush=True)

print("STEP 2: waiting for approval (polling)...", flush=True)
deadline = time.time() + dc.get("expires_in", 900)
token = None
while time.time() < deadline:
    time.sleep(dc.get("interval", 5))
    try:
        res = post("https://github.com/login/oauth/access_token", {
            "client_id": CLIENT_ID,
            "device_code": dc["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    except Exception as e:
        print("poll error: %s" % e, flush=True)
        continue
    if "access_token" in res:
        token = res["access_token"]
        break
    if res.get("error") not in ("authorization_pending", "slow_down"):
        print("FLOW_FAILED: %s" % res.get("error_description", res.get("error")), flush=True)
        sys.exit(1)

if not token:
    print("FLOW_EXPIRED: user did not approve in time", flush=True)
    sys.exit(2)

# verify + get username (token stays in memory only)
req = urllib.request.Request("https://api.github.com/user",
    headers={"Authorization": "Bearer " + token,
             "Accept": "application/vnd.github+json",
             "User-Agent": "deons-deals-setup"})
with urllib.request.urlopen(req, timeout=30) as r:
    me = json.load(r)
username = me["login"]

# store in gh's config (same place `gh auth login` writes)
cfg_dir = os.path.expanduser("~/.config/gh")
os.makedirs(cfg_dir, exist_ok=True)
path = os.path.join(cfg_dir, "hosts.yml")
with open(path, "w") as f:
    f.write("github.com:\n    user: %s\n    oauth_token: %s\n    git_protocol: https\n"
            % (username, token))
os.chmod(path, 0o600)
print("LOGIN_OK user=%s" % username, flush=True)
