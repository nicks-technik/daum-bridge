# Email delivery (TCX attachments)

daum-bridge can email every finished training as a TCX attachment. It is an
alternative (or addition) to the Strava API upload and works without any
Strava subscription: download or forward the `.tcx` and upload it at
<https://www.strava.com/upload/select>.

## Configuration

Add an `email:` section to `config.yaml`:

```yaml
email:
  auto_send: true            # email every ride automatically when it finishes
  host: "smtp.gmail.com"
  port: 587                  # 587 = STARTTLS, 465 = implicit SSL
  username: "you@gmail.com"
  password: "your-app-password"
  from_addr: "you@gmail.com"
  to_addr: "you@gmail.com"   # comma-separated recipients allowed
  use_tls: true              # STARTTLS
  use_ssl: false             # implicit TLS (true for port 465)
  subject_prefix: "Daum training"
```

The same values can be supplied through environment variables (handy for
Docker or a systemd unit):

| Setting | Environment variable |
| --- | --- |
| `host` | `DAUM_EMAIL_HOST` |
| `port` | `DAUM_EMAIL_PORT` |
| `username` | `DAUM_EMAIL_USER` |
| `password` | `DAUM_EMAIL_PASSWORD` |
| `from_addr` | `DAUM_EMAIL_FROM` |
| `to_addr` | `DAUM_EMAIL_TO` |
| `use_tls` | `DAUM_EMAIL_TLS` |
| `use_ssl` | `DAUM_EMAIL_SSL` |
| `auto_send` | `DAUM_EMAIL_AUTO_SEND` |
| `subject_prefix` | `DAUM_EMAIL_SUBJECT_PREFIX` |

`host`, `from_addr` and `to_addr` are required; `username`/`password` are
optional for SMTP servers that do not require authentication.

## Sending a ride

**Automatically:** set `email.auto_send: true` (or `DAUM_EMAIL_AUTO_SEND=true`).
The mail is sent in the background once the ride has been saved, so the
bridge is not blocked.

**Web UI:** open `/downloads` (all trainings, newest first) and press
**Email** on a ride, or use **Email latest TCX** on `/history`. After
finishing a ride from the dashboard, the **Email TCX** link appears next to
the download link.

**CLI:**

```bash
# Email the most recent ride to the configured recipient
uv run daum-bridge email-ride

# Send a specific ride to another address
uv run daum-bridge email-ride --ride rides/2026-10-29T18-00-00.json --to me@example.com
```

## Gmail and other providers

Gmail no longer accepts your normal account password for SMTP. Create an
app password (Google account → Security → 2-Step Verification → App
passwords) and use that as `password`. Other providers usually accept the
normal password or a dedicated SMTP/app password:

| Provider | Host | Port | Notes |
| --- | --- | --- | --- |
| Gmail | `smtp.gmail.com` | 587 (STARTTLS) | requires an app password |
| Outlook/Office 365 | `smtp.office365.com` | 587 (STARTTLS) | OAuth or app password depending on tenant |
| GMX | `mail.gmx.net` | 587 (STARTTLS) | normal password |
| Mailbox.org | `smtp.mailbox.org` | 465 (SSL) | set `use_ssl: true`, `use_tls: false` |

## Troubleshooting

- **`Email is not configured`** — `host`, `from_addr` or `to_addr` is empty.
  Remember that config values are read at startup; restart the bridge after
  changing `config.yaml` on the Config page.
- **`SMTPAuthenticationError`** — wrong password or a provider that requires
  an app password / OAuth. For Gmail use an app password.
- **Connection timeout** — check the port/firewall. Port 587 usually needs
  STARTTLS (`use_tls: true`); port 465 needs `use_ssl: true` and
  `use_tls: false`.
- **Mail goes to spam** — send from the same address you authenticate with
  (`from_addr` = `username`) and add SPF/DKIM records if you run your own
  mail server.
- **No mail after a ride** — check `auto_send`, and look for `ride-email` /
  `Email` lines in the bridge logs. A manual send from `/downloads` shows the
  error message directly.
