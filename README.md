# statbot

A small Telegram bot that nags about VPS. Once an hour it sends a report with
CPU load, RAM and disk usage, running Docker containers, and how hard the box has
been getting brute-forced over ssh in the last 24 hours.

You can also ask it directly:

- `/stats` — same report, right now
- `/logins` — brute-force activity: how many failed attempts there were in the
  last 24 hours, from how many IPs, with an hourly chart attached

The hourly report carries the same chart as a photo.

Both only work for the admin user (the one from `ADMIN_ID`), everyone else gets
ignored. The journal lines contain IPs of random people trying to brute-force the
box, so I'd rather not hand those out.

## Running

Needs Python 3.13 and [uv](https://docs.astral.sh/uv/). Copy `.env.example` to
`.env` and fill in the values:

```
BOT_TOKEN=...      # from @BotFather
ADMIN_ID=...       # your Telegram user id
```

Then:

```
uv sync
uv run src/main.py
```

On the server I just run it under systemd. The unit is:

```ini
[Unit]
Description=statbot
After=network.target

[Service]
WorkingDirectory=/opt/bots/statbot
ExecStart=/opt/bots/statbot/.venv/bin/python src/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Reading sshd logs from the journal requires being root or in the `systemd-journal`
group. Same story for the Docker socket — if the bot can't reach it, you'll get a
"check Docker socket rights" line in the report instead of container names. That's
a feature, kind of.

## Deploy

Everything is automated with a GitHub Actions workflow (`.github/workflows/deploy.yml`):
push to `main`, the whole repo gets scp'd to `/opt/bots/statbot`, then over ssh it
runs `uv sync` and restarts the systemd service.

Three repo secrets are needed: `SERVER_HOST`, `SERVER_USER`, `SSH_PRIVATE_KEY`
(a deploy key that's allowed to log into the box as that user).

`.env` is not in the repo and does not get deployed — it lives on the server and
only has to be created once.

## Notes worth remembering

- Python is pinned to 3.13 on deploy (`uv sync -p 3.13`) because the box doesn't
  have a compiler, and on 3.15 `pydantic-core` has no wheel yet, so uv tries to
  build it from source and fails. If that ever changes, the pin can go.
- `journalctl -u ssh -u sshd` covers both service names; on Ubuntu the unit is
  called `ssh`, all upstream docs assume `sshd`.
