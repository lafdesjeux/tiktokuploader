# TikTok Desktop Publisher

## Release 1.0.1

Fixes the desktop GUI startup status label on Tkinter.


A reusable desktop application and command-line tool for creators who want to authorize their own TikTok account, select a local video, choose the privacy and interaction settings returned by TikTok, and publish through the official Content Posting API.

The project is intentionally generic:

- no creator name, account identifier, token, or local path is embedded;
- each user completes TikTok Login Kit OAuth for their own account;
- creator information is queried immediately before export;
- privacy choices are populated from TikTok's current `privacy_level_options`;
- explicit user consent is required before publishing or scheduling;
- future publication dates are stored in a local SQLite queue because the Direct Post endpoint does not provide native scheduling;
- tokens are stored in the operating-system keyring when available, with a user-only local fallback.

## Screens shown during app review

1. **Account** — creator-facing TikTok OAuth, authorized account, and current privacy options.
2. **Publish** — video picker, caption, privacy, comments/Duet/Stitch controls, commercial-content and AI labels, explicit consent.
3. **Local queue** — scheduled jobs and due-job execution.
4. **Settings** — operator-only app credentials and desktop redirect URI.
5. **Logs** — API and upload progress without displaying tokens.

## Requirements

- Python 3.10+
- Tkinter (normally included with Python on Windows and macOS; install the distribution package on Linux)
- A TikTok developer app with Login Kit and Content Posting API
- Approved scopes: `user.info.basic` and `video.publish`
- Desktop redirect URI, for example `http://127.0.0.1:3455/callback/`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

## Run the graphical interface

```bash
python run_gui.py
```

or after installation:

```bash
tiktok-publisher-gui
```

The application operator configures the TikTok app client key, client secret, and redirect URI once in **Settings**. Creators then use **Account → Connect with TikTok**; the browser handles login and consent. Tokens are not written to this repository.

## CLI compatibility

Connect an account:

```bash
python tiktok_publish.py \
  --client-key "YOUR_CLIENT_KEY" \
  --client-secret "YOUR_CLIENT_SECRET" \
  --redirect-uri "http://127.0.0.1:3455/callback/" \
  --connect
```

Publish immediately:

```bash
python tiktok_publish.py \
  --video "/path/to/video.mp4" \
  --post "Caption #example" \
  --privacy-level SELF_ONLY \
  --consent \
  --wait
```

Schedule locally for a future date:

```bash
python tiktok_publish.py \
  --video "/path/to/video.mp4" \
  --post "Caption #example" \
  --privacy-level SELF_ONLY \
  --tiktok-date "2026-08-01 18:00" \
  --consent
```

Publish all due jobs:

```bash
python tiktok_publish.py --run-due --wait
```

The existing `--game` and `--platform` arguments are accepted for compatibility with external workflows but are not required by the generic app.

## Scheduling

A future date creates a local queue entry. Run `--run-due` periodically with cron, launchd, or Task Scheduler. A past or missing date publishes immediately.

Example cron entry, every five minutes:

```cron
*/5 * * * * /absolute/path/.venv/bin/python /absolute/path/tiktok_publish.py --run-due
```

## Security

- Never commit `.env`, access tokens, refresh tokens, or client secrets.
- OAuth uses a random anti-CSRF state value and desktop PKCE.
- The redirect listener accepts only the configured loopback callback.
- Token output is never written to the GUI log.
- Users can revoke access with the **Disconnect** button.

## Unreviewed clients

TikTok restricts content posted by unaudited clients to private viewing. Use `SELF_ONLY` while testing, and demonstrate the complete flow in the TikTok Developer sandbox.

## Website and policies

- Website: `https://lafdesjeux.github.io/RetroReelsUploader/`
- Privacy: `https://lafdesjeux.github.io/RetroReelsUploader/privacy.html`
- Terms: `https://lafdesjeux.github.io/RetroReelsUploader/terms.html`

## License

MIT
