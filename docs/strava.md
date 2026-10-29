# Strava upload

daum-bridge can save every finished ride as a TCX activity on Strava,
either manually from the web UI / CLI or automatically when a ride ends.
Strava no longer allows creating activities directly through its API, so
the bridge uploads a generated TCX file to the
[`/uploads`](https://developers.strava.com/docs/uploads/) endpoint and
waits until Strava has processed it.

## Do I need a Strava subscription?

**For API uploads: yes.** Since June 2026 Strava requires an active Strava
subscription to use the public API as a Standard Tier developer — that
includes a personal app used by a single athlete (up to 10 athletes).
There is no separate API fee; the subscription itself is the prerequisite.
New apps were affected from 1 June 2026, existing apps from 30 June 2026.
Without a subscription the `Upload to Strava` button and
`daum-bridge strava-upload` cannot authenticate.

**For manual uploads: no.** Uploading a finished ride through Strava's
website is free and does not use the API:

1. Open `/downloads` (all trainings, newest first) and click **Download TCX**
   on the ride — or use `/history`, or run
   `uv run daum-bridge export-tcx` (optionally with `--ride <file>`).
2. Go to <https://www.strava.com/upload/select> and drop the `.tcx` file
   into the page.

You can also have every finished ride mailed to yourself as a TCX
attachment — see [email.md](email.md).

The remainder of this page covers the optional API integration.

## What gets uploaded

- One activity per recorded ride (activity type `Ride`, trainer flag set).
- Power, cadence and heart rate from the Daum `run_Data`/`person_Data`
  frames, sampled once per second.
- Distance from the cockpit odometer (0.1 km resolution), falling back to
  integrating the speed value. There is no GPS data, so the activity has
  no map.
- Calories are approximated from mechanical work (1 kJ ≈ 1 kcal).

Every ride is stored locally in `rides/<ride-id>.json` (override the
directory with `DAUM_RIDES_DIR`), including the raw samples. The JSON file
is what makes it possible to upload a ride later, even after a restart.

## 1. Create a Strava API application

1. Open <https://www.strava.com/settings/api>.
2. Create an application. Any name/category works.
3. Set **Authorization Callback Domain** to `localhost`.
4. Note the **Client ID** and **Client Secret**.

## 2. Authorize daum-bridge

Run the interactive helper once:

```bash
uv run daum-bridge strava-auth --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET> --write-config
```

It prints an authorization URL:

1. Open the URL in a browser, log in to Strava and click **Authorize**.
2. The browser is redirected to `http://localhost/?state=...&code=...`.
   The page itself will fail to load — that is expected.
3. Copy the complete URL from the address bar and paste it into the
   prompt (a bare authorization code also works).

The helper exchanges the code for tokens, caches the access/refresh token
in `strava.tokens.json` (mode `0600`) and, with `--write-config`, stores
the client credentials and refresh token in `config.yaml`.

Instead of `--write-config` you can use environment variables:

| Variable | Purpose |
| --- | --- |
| `STRAVA_CLIENT_ID` | Strava API client id |
| `STRAVA_CLIENT_SECRET` | Strava API client secret |
| `STRAVA_REFRESH_TOKEN` | Refresh token from `strava-auth` |
| `STRAVA_ACCESS_TOKEN` | Optional short-lived access token |
| `STRAVA_TOKENS_FILE` | Token cache path (default `strava.tokens.json`) |
| `STRAVA_AUTO_UPLOAD` | `1`/`true` to upload finished rides automatically |
| `STRAVA_PRIVATE` | `1`/`true` to upload activities as private |

Access tokens expire after a few hours; the bridge refreshes them
automatically and writes the new token to the cache file.

## 3. Upload rides

**Manual, free (no subscription, no API app):**

```bash
# Export the most recent ride to rides/<ride-id>.tcx, then upload it at
# https://www.strava.com/upload/select
uv run daum-bridge export-tcx

# Export a specific ride to a chosen path
uv run daum-bridge export-tcx --ride rides/2026-10-29T18-00-00.json --output ~/ride.tcx
```

The TCX file is written automatically next to the ride JSON
(`rides/<ride-id>.tcx`) when the ride finishes, so it can be uploaded right
away. The downloads page (`/downloads`) lists all trainings newest first with
a **Download TCX** link; the history page has the same link per ride.

**API upload (requires a Strava subscription):**

Open `/history` and use *Upload latest to Strava* or the *Upload* button
on a specific ride.

**CLI:**

```bash
# Upload the most recent ride
uv run daum-bridge strava-upload

# Upload a specific ride file, as a private activity
uv run daum-bridge strava-upload --ride rides/2026-10-29T18-00-00.json --private
```

**Automatically after each ride** — in `config.yaml`:

```yaml
strava:
  auto_upload: true
  private: false
```

**HTTP API:**

- `GET /api/strava/status` — whether credentials are configured, plus the
  result of the last upload.
- `POST /api/strava/upload` — body `{}` uploads the latest ride, or
  `{"ride_id": "<id>"}` a specific one. Optional `name` / `description`
  override the generated activity name and description.

## Configuration reference

```yaml
strava:
  auto_upload: false    # upload a ride as soon as it finishes
  private: false        # upload activities as private
  client_id: ""
  client_secret: ""
  refresh_token: ""     # obtained with `daum-bridge strava-auth`
  token_file: "strava.tokens.json"
  poll_timeout: 120     # seconds to wait for Strava to process an upload
```

`config.yaml`, `rides/` and `strava.tokens.json` are git-ignored because
they contain credentials and personal activity data.

## Troubleshooting

- **"Strava is not configured"** — run `strava-auth` or set
  `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` and `STRAVA_REFRESH_TOKEN`.
- **`Strava API error (401)`** — the refresh token is no longer valid
  (revoked app, changed password). Re-run `strava-auth`.
- **`403` / subscription required** — since June 2026, Strava API access
  requires an active Strava subscription on the API app owner's account.
  Use **Download TCX** + <https://www.strava.com/upload/select> instead.
- **Upload rejected (400)** — check the bridge log for Strava's message.
  A duplicate upload returns "duplicate of activity ...". Delete the
  Strava activity or upload a different ride.
- **Upload timed out** — Strava occasionally takes longer to process a
  file; increase `strava.poll_timeout` and retry. The activity may still
  appear on Strava.
- **Distance is 0 km** — the cockpit did not report an odometer value and
  the speed field was empty. The activity still contains power and heart
  rate.
- **Tests / CI** — no network calls are made unless Strava credentials are
  configured; unit tests fake the HTTP layer.
