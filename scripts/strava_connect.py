#!/usr/bin/env python3
"""
strava_connect.py — One-time Strava OAuth connect for OMPB (standard library only).

Strava has no "paste a token" path: every token is bound to your own Strava API application,
and access tokens expire every 6 hours (refreshing needs the app's client_id + client_secret).
So the seamless flow is: you create your *own* personal Strava app once (no review needed for
your own data), then this script runs the OAuth dance automatically via a localhost callback —
you only click "Authorize" in the browser. It writes a refresh-token credential file that
`import_strava.py` then uses to auto-refresh access tokens forever.

What you create once at https://www.strava.com/settings/api :
  - Application Name: anything (e.g. "my-ompb")
  - Category: Data Importer
  - Authorization Callback Domain: localhost      <-- IMPORTANT, must be exactly "localhost"
Then copy the Client ID and Client Secret and pass them here.

Usage:
  python3 strava_connect.py --client-id 12345 --client-secret abc... [--home DIR] [--port 8721]
  (client id/secret may also come from $STRAVA_CLIENT_ID / $STRAVA_CLIENT_SECRET, or be prompted)

Writes: $OMPB_HOME/strava.json  {client_id, client_secret, refresh_token, access_token,
expires_at, athlete_id, connected_at}  (chmod 600 — contains secrets, never commit it).
"""

import argparse
import http.server
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone

from ompb_env import resolve_home

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
DEFAULT_SCOPE = "activity:read_all"


class _Handler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        _Handler.result = {k: v[0] for k, v in q.items()}
        ok = "code" in _Handler.result and "error" not in _Handler.result
        body = (
            "<html><body style='font-family:sans-serif;text-align:center;padding-top:80px'>"
            + ("<h2>✓ Strava connected</h2><p>You can close this tab and return to your terminal.</p>"
               if ok else
               "<h2>✗ Authorization failed</h2><p>%s — try again.</p>" % _Handler.result.get("error", "denied"))
            + "</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):  # silence default request logging
        pass


def _post_token(params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main(argv=None):
    ap = argparse.ArgumentParser(description="One-time Strava OAuth connect for OMPB.")
    ap.add_argument("--client-id", default=os.environ.get("STRAVA_CLIENT_ID"))
    ap.add_argument("--client-secret", default=os.environ.get("STRAVA_CLIENT_SECRET"))
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--port", type=int, default=8721)
    ap.add_argument("--scope", default=DEFAULT_SCOPE)
    ap.add_argument("--no-browser", action="store_true", help="Print the URL instead of opening a browser.")
    args = ap.parse_args(argv)

    client_id = args.client_id or input("Strava Client ID: ").strip()
    client_secret = args.client_secret or input("Strava Client Secret: ").strip()
    if not client_id or not client_secret:
        sys.stderr.write("error: client id and secret are required (create an app at "
                         "https://www.strava.com/settings/api).\n")
        return 2

    redirect_uri = f"http://localhost:{args.port}/callback"
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "approval_prompt": "force",
        "scope": args.scope,
    })

    server = http.server.HTTPServer(("localhost", args.port), _Handler)
    t = threading.Thread(target=server.handle_request)  # serve exactly one request
    t.start()

    sys.stderr.write(f"# Opening browser to authorize OMPB on your Strava account...\n#   {auth_url}\n")
    if not args.no_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass
    t.join(timeout=300)
    server.server_close()

    res = _Handler.result
    if "code" not in res:
        sys.stderr.write(f"error: no authorization code received ({res.get('error', 'timeout')}).\n")
        return 1

    tok = _post_token({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": res["code"],
        "grant_type": "authorization_code",
    })
    if "refresh_token" not in tok:
        sys.stderr.write(f"error: token exchange failed: {tok}\n")
        return 1

    home = resolve_home(args.home, create=True)
    cred_path = os.path.join(home, "strava.json")
    cred = {
        "client_id": str(client_id),
        "client_secret": client_secret,
        "refresh_token": tok["refresh_token"],
        "access_token": tok.get("access_token"),
        "expires_at": tok.get("expires_at"),
        "athlete_id": (tok.get("athlete") or {}).get("id"),
        "connected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(cred_path, "w", encoding="utf-8") as fh:
        json.dump(cred, fh, indent=2)
    os.chmod(cred_path, 0o600)  # secrets: owner read/write only

    ath = tok.get("athlete") or {}
    who = (" ".join(filter(None, [ath.get("firstname"), ath.get("lastname")])) or ath.get("id") or "athlete")
    sys.stderr.write(f"# ✓ Connected as {who}. Credentials saved to {cred_path} (chmod 600 — do not commit).\n")
    sys.stderr.write("#   Next: python3 import_strava.py  (syncs your activities; auto-refreshes tokens)\n")
    print(cred_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
