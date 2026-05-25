---
name: pb-connect-strava
description: Connect a Strava account and sync activities (one-time setup, then auto-refresh)
argument-hint: "[--client-id ID --client-secret SECRET] or just run it and follow the prompts"
level: 3
---

<Purpose>
Connects the runner's Strava account so activities sync into the training log and keep syncing
without re-auth. Strava has no "paste a token" path — every token is bound to a Strava API app
and access tokens expire every 6 hours — so the seamless flow is: the runner creates their OWN
personal Strava app once (no review needed for their own data), then this skill runs the OAuth
dance automatically via a localhost callback (the runner only clicks "Authorize" in the browser)
and stores a refresh-token credential that `import_strava.py` auto-refreshes from then on.
</Purpose>

<Use_When>
- The runner wants to import from Strava, or says "connect strava", "스트라바 연동", "sync strava"
- During `/pb-setup` when the runner picks Strava as their data source
- A **Garmin or COROS** user who wants auto-sync: those platforms have no individual API (business/partner-only), but both watches can auto-sync to Strava with one toggle in their app — so connecting Strava here pulls their Garmin/COROS activities too. (Prefer this over the gated/undocumented Garmin/COROS APIs.)
</Use_When>

<Do_Not_Use_When>
- The runner only has COROS/Garmin `.fit` files or a CSV → use `/pb-log` (no Strava app needed)
- They just want a one-time dump and don't want to make an app → suggest Strava's "Request your archive" (Settings → My Account) and import the resulting `.fit`/CSV via `/pb-log`
</Do_Not_Use_When>

<Steps>

## Step 1 — Create a personal Strava app (one-time, ~2 min, no review)
Tell the runner to open **https://www.strava.com/settings/api** and create an app with these exact values:
- **Application Name:** anything (e.g. `my-ompb`)
- **Category:** Data Importer
- **Club:** leave blank
- **Website:** anything (e.g. `http://localhost`)
- **Authorization Callback Domain:** `localhost`  ← MUST be exactly this, or the connect step fails
Then copy the **Client ID** and **Client Secret** from that page.

> This app is private to the runner and only ever touches their own data. App *review* is only
> required to let *other* athletes connect — not for personal single-user use.

## Step 2 — Run the OAuth connect (automated)
With the runner's Client ID and Client Secret:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/strava_connect.py" --client-id <ID> --client-secret <SECRET>
```
This opens the browser to Strava's authorize page (scope `activity:read_all`), runs a one-shot
localhost callback server, captures the returned code, exchanges it, and writes
`$OMPB_HOME/strava.json` (chmod 600 — contains secrets, gitignored, never commit). The runner
only clicks **Authorize**. If no browser opens (headless), re-run with `--no-browser` and have
them open the printed URL manually. The command blocks until they authorize (≤5 min timeout).

## Step 3 — First sync
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_strava.py"
```
Refreshes the access token automatically, pages through all activities, normalizes them
(running → easy/long, other sports → cross), and appends new ones to
`$OMPB_HOME/training-log.jsonl` (deduped by `source_id`). Report the summary (new activities, by sport).

## Step 4 — Hand off
- If the runner is new, continue `/pb-setup` (profile bootstrap + first deck).
- Ongoing: re-run `import_strava.py` (or `/pb-log strava`) anytime to pull new activities — no
  re-auth needed; the stored refresh token mints fresh access tokens.

</Steps>

<Security>
- `strava.json` holds `client_secret` + `refresh_token`. It lives under `$OMPB_HOME` (gitignored) and is written chmod 600. Never print the secret, never commit the file.
- Scope is `activity:read_all` (read-only, includes private activities). OMPB never writes to Strava.
</Security>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset (not an installed plugin) → run the scripts from the repo with `python3 scripts/...`.
- Token exchange/refresh fails → most often the Callback Domain wasn't `localhost`, or the client id/secret were mistyped; have the runner re-check the app settings and retry.
- Strava API returns 429 → rate limited; wait 15 minutes and re-run (sync resumes via dedup).
</Stop_Conditions>
