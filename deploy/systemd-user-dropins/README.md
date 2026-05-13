# DS4 Systemd Drop-In Examples (`systemd --user`)

This directory contains **example** systemd drop-in snippets for the templates in `deploy/systemd-user/`.

Nothing here is applied automatically.

## Recommended Workflow (Human-Run)

Prefer `systemctl --user edit` so systemd writes the drop-in to the correct location:

```bash
# Instance-specific:
systemctl --user edit ds4@spark0.service

# Or template-wide:
systemctl --user edit ds4@.service
```

Then reload and restart:

```bash
systemctl --user daemon-reload
systemctl --user restart ds4@spark0.service
```

## If You Prefer Copying Files (Human-Run)

Copy a snippet into:

- `~/.config/systemd/user/ds4@.service.d/<name>.conf`

Docs:

- User-service runbook: `docs/deployment-systemd-user.md`

