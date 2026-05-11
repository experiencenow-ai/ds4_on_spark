# Ops: Prometheus Alerting (DS4)

This is a **human-run** reference for wiring DS4 metrics into Prometheus alerting.

This repo does not enable or modify Prometheus/Alertmanager automatically.

## Inputs From This Repo

- Scrape snippet: `deploy/config/prometheus-scrape.ds4.yml.example`
- Alert rule snippet: `deploy/config/prometheus-alerts.ds4.yml.example`

Both examples assume DS4 exports a Prometheus endpoint at:

- `http://<spark-host>:9090/metrics`

Adjust hostnames/IPs and port to match your actual `DS4_METRICS_{ADDR,PORT}`.

## Label Conventions

Prefer stable, low-cardinality labels:

- `ds4_instance`: `spark0|spark1|spark2|spark3`

Avoid labels derived from user prompts, request contents, or other unbounded values.

## Load Rules (Example)

Prometheus supports `rule_files:` in its config. Example (human-run; path depends on your Prometheus host):

```bash
install -d -m 0755 /etc/prometheus/rules
cp deploy/config/prometheus-alerts.ds4.yml.example /etc/prometheus/rules/ds4-alerts.yml
```

Then add to Prometheus config:

```yaml
rule_files:
  - /etc/prometheus/rules/ds4-alerts.yml
```

Reload Prometheus per your host policy (often via systemd or a reload endpoint).

## Testing (Safe)

After loading:

- Confirm Prometheus config/rule health via your Prometheus UI.
- Verify DS4 targets are `UP` and carry the expected `ds4_instance` label.
- If you do not have DS4 metrics yet, `DS4TargetDown` still works because it only depends on `up{job="ds4"}`.

