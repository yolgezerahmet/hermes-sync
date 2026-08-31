# A2A Inbox Worker systemd birimleri (H1/H3 Linux)

Hedef: `/etc/systemd/system/a2a-inbox-worker.service` + `.timer`

## Servis

```ini
[Unit]
Description=Cumulus A2A allowlisted update worker
After=network-online.target a2a-mesh.service
Wants=network-online.target

[Service]
Type=oneshot
User=root
EnvironmentFile=/root/.hermes/.env
WorkingDirectory=/root/.hermes/scripts
ExecStart=/usr/bin/python3 /root/.hermes/scripts/inbox_worker.py
```

## Timer (5 dk)

```ini
[Unit]
Description=Run Cumulus A2A allowlisted update worker every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

## Kurulum

```bash
cp systemd/a2a-inbox-worker.service systemd/a2a-inbox-worker.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now a2a-inbox-worker.timer
```

Not: worker, `/root/.hermes/scripts/inbox_worker.py` (veya platform karşılığı) üzerinden
çalışır; `inbox_worker.py` script kopyası her güncelleme paketiyle senkron tutulur.
