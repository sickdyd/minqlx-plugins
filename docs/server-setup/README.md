# Server setup (Shanghai CA / qlove)

Reference documentation for the production deployment that runs these plugins.
It covers the LinuxGSM + minqlx layout, the two Quake Live instances, the
systemd services, the cron jobs, and the backup script.

> **Secrets:** every credential in the files below has been replaced with a
> `<PLACEHOLDER>`. Real values (`g_password`, `sv_privatePassword`,
> `zmq_rcon_password`, `zmq_stats_password`, `qlx_owner`, the public IP, the
> LinuxGSM `secrets-*.cfg` files, and rclone/Backblaze credentials) live only
> on the server and must **never** be committed.

## Overview

```
Ubuntu VM
├── LinuxGSM (qlserver)                two QL dedicated instances
│   ├── qlserver        -> port 27960
│   └── qlserver-2      -> port 27961
├── minqlx                              mod loaded via LD_PRELOAD
│   └── minqlx-plugins  (this repo)     qlx_plugins list below
└── qlove (Docker)                      Rails API + Postgres + frontend
    └── leaderboards plugin -> http://localhost:3000
```

Both QL instances run from the same `serverfiles/` and the same plugin set;
they differ only by `net_port` and their `*.cfg`.

## Loaded plugins (`qlx_plugins`)

```
plugin_manager, essentials, motd, permission, ban, silence, clan, names, log,
balance, workshop, autospec, mybalance, player_info, leaderboards
```

- Stock MinoMino plugins provide the base (`plugin_manager` … `workshop`).
- `autospec`, `mybalance`, `player_info` are iouonegirl plugins (depend on the
  bundled `iouonegirl.py` superclass; it is auto-loaded, not listed in
  `qlx_plugins`).
- `leaderboards` is the custom plugin that talks to the qlove API
  (`qlx_qloveLeaderboardsHost`, default `http://localhost:3000`).
- `forcejoin` (in this repo) is **not yet enabled** on the server.

## Files in this directory

| Path | Source on server | Notes |
|------|------------------|-------|
| `systemd/qlserver.service`   | `/etc/systemd/system/qlserver.service`   | instance 1, port 27960 |
| `systemd/qlserver-2.service` | `/etc/systemd/system/qlserver-2.service` | instance 2, port 27961 |
| `lgsm/config-lgsm/qlserver/common.cfg`     | LinuxGSM common settings | |
| `lgsm/config-lgsm/qlserver/qlserver.cfg`   | LinuxGSM instance 1 | |
| `lgsm/config-lgsm/qlserver/qlserver-2.cfg` | LinuxGSM instance 2 | sets `port` / `startparameters` |
| `baseq3/qlserver.cfg`   | `serverfiles/baseq3/qlserver.cfg`   | **sanitized** game cfg, instance 1 |
| `baseq3/qlserver-2.cfg` | `serverfiles/baseq3/qlserver-2.cfg` | **sanitized** game cfg, instance 2 |
| `baseq3/server.cfg`     | `serverfiles/baseq3/server.cfg`     | **sanitized** shared/base cfg |
| `scripts/qlove-backup.sh` | `~/scripts/qlove-backup.sh` | nightly Postgres dump → Backblaze B2 |
| `crontab.txt` | `crontab -l` (user `qlserver`) | backups, restarts, qlove maintenance |

## Services

Each instance is a `Type=simple` systemd unit running `qzeroded.x64` with
`LD_PRELOAD=./minqlx.x64.so` from `serverfiles/`, restarting on failure.
Manage them with:

```bash
sudo systemctl status qlserver
sudo systemctl restart qlserver-2
journalctl -u qlserver -f
```

## Scheduled jobs (cron)

- **03:00** — `qlove-backup.sh`: `pg_dump` of `qlove_production` from the
  `qlove-qpg-1` container, uploaded to Backblaze B2 via `rclone`, with size-based
  rotation (keeps the bucket under 10 GB).
- **04:00 / 05:00** — staggered restarts of `qlserver` / `qlserver-2`.
- **04:05** — restart of the qlove Docker stack.
- **00:00** — `rails elo:snapshot` inside the qlove API container.

See `crontab.txt` for the exact entries.

## Restoring on a new box (outline)

1. Install LinuxGSM and the QL server (`./qlserver install`), then minqlx.
2. Drop this repo into `serverfiles/minqlx-plugins` and
   `pip install -r requirements.txt`.
3. Copy the `baseq3/*.cfg` files in and fill the `<PLACEHOLDER>` secrets.
4. Recreate the LinuxGSM `secrets-*.cfg` files (Steam login / GSLT).
5. Install the `systemd/*.service` units, `systemctl enable --now` both.
6. Reinstall the crontab and `rclone` config for backups.
