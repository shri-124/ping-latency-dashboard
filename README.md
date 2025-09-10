# Ping & Latency Dashboard


Probe multiple targets (HTTP and TCP), export Prometheus metrics, alert when latency > threshold, and visualize in Grafana.


## Quick start


```bash
# 1) Clone and enter
# git clone <this-repo> && cd repo


# 2) Start the stack
docker compose up -d --build


# 3) Open UIs
# Prometheus: http://localhost:9090
# Alertmanager: http://localhost:9093
# Grafana: http://localhost:3000 (anonymous viewer enabled)
# Pinger: http://localhost:8000/metrics
```


## Configure targets
Edit `config/targets.yml` (URL + `threshold_seconds`). Supports:
- `https://…` / `http://…` — full request latency (redirects followed)
- `tcp://host:port` — TCP connect handshake latency


Change intervals/timeouts globally at the top of that file or via env:
- `SCRAPE_INTERVAL_SECONDS` (default 15)
- `REQUEST_TIMEOUT_SECONDS` (default 5)


Prometheus rule fires **HighLatency** when:
```
ping_latency_seconds > ping_latency_threshold_seconds
```
… and **TargetDown** when `ping_up == 0` for 2m.


## How alerts are delivered
By default, Alertmanager posts to the pinger webhook at `POST /alert` and the app logs the payload. To send real notifications:
1. Add a Slack or email receiver to `alertmanager/alertmanager.yml`.
2. Restart Alertmanager: `docker compose restart alertmanager`.


## Add more probes
Append to `config/targets.yml` and wait one cycle (or restart pinger). No Prometheus changes needed.


## Common tasks
- Live reload Prometheus after rules changes:
```bash
curl -X POST http://localhost:9090/-/reload
```
- Tail pinger logs to see alerts hit the webhook:
```bash
docker logs -f pinger
```


## InfluxDB option (optional)
This starter uses Prometheus. If you prefer InfluxDB, replace Prometheus/Alertmanager with Telegraf + InfluxDB and write points from the app. (Open an issue and we can drop in a minimal `influxdb` compose service + write API snippet.)


## Security notes
- This demo enables anonymous Grafana for speed. Disable for real deployments.
- The pinger follows redirects; endpoints requiring auth aren’t supported in this MVP.
