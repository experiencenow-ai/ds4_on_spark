# DS4 Systemd Drop-In Examples (System Units)

This directory contains **example** systemd drop-in snippets you can use to override/tune the templates in `deploy/systemd/` without editing the base unit files.

Nothing here is applied automatically.

## Recommended Workflow (Human-Run)

Prefer `systemctl edit` so systemd writes the drop-in to the correct location:

```bash
# Instance-specific (recommended for experimentation):
sudo systemctl edit ds4@spark0.service

# Or template-wide (applies to all instances):
sudo systemctl edit ds4@.service
```

Then add directives under a `[Service]` section and reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ds4@spark0.service
```

## If You Prefer Copying Files (Human-Run)

Copy a snippet from this repo into the standard drop-in directory:

```bash
sudo install -d -m 0755 /etc/systemd/system/ds4@.service.d
sudo install -m 0644 deploy/systemd-dropins/ds4@.service.d/20-timeouts.conf.example \
  /etc/systemd/system/ds4@.service.d/20-timeouts.conf
sudo systemctl daemon-reload
```

Notes:

- Drop-ins must end in `.conf` to take effect.
- Use instance-specific drop-ins (`/etc/systemd/system/ds4@spark0.service.d/...`) when you want to tune one host without affecting the whole fleet.

Docs:

- Systemd overview: `docs/deployment-systemd.md`
- Spark0/Spark1/Spark2 layout: `docs/deployment-spark0-spark1-spark2.md`
- Ops checklist: `docs/spark-ring-ops-checklist-tp3.md`

