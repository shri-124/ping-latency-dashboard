import os
import time
import socket
import asyncio
import yaml
from typing import List, Dict, Tuple

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from prometheus_client import Gauge, Counter, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST


# ---- Config ----
TARGETS_FILE = os.getenv("TARGETS_FILE", "/config/targets.yml")
ENV_SCRAPE_INTERVAL = float(os.getenv("SCRAPE_INTERVAL_SECONDS", "15"))
ENV_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))


# ---- Metrics ----

REGISTRY = CollectorRegistry()
LATENCY = Gauge(
"ping_latency_seconds",
"Measured end-to-end latency for a target",
labelnames=("name", "scheme", "target"),
registry=REGISTRY,
)

UP = Gauge(
"ping_up",
"1 if last probe succeeded, otherwise 0",
labelnames=("name", "scheme", "target"),
registry=REGISTRY,
)

THRESH = Gauge(
"ping_latency_threshold_seconds",
"Alert threshold per target (seconds)",
labelnames=("name", "scheme", "target"),
registry=REGISTRY,
)

ERRORS = Counter(
"ping_errors_total",
"Total probe errors",
labelnames=("name", "scheme", "target"),
registry=REGISTRY,
)

app = FastAPI(title="Ping & Latency Pinger")

state: Dict = {
"targets": [],
"interval": ENV_SCRAPE_INTERVAL,
"timeout": ENV_TIMEOUT,
}

def load_config(path: str) -> Tuple[List[Dict], float, float]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    targets = cfg.get("targets", [])
    interval = float(cfg.get("interval_seconds", state["interval"]))
    timeout = float(cfg.get("request_timeout_seconds", state["timeout"]))
    return targets, interval, timeout

async def probe_http(url: str, timeout: float) -> float:
    start = time.perf_counter()
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return time.perf_counter() - start

async def probe_tcp(host: str, port: int, timeout: float) -> float:
    start = time.perf_counter()
    fut = asyncio.open_connection(host=host, port=port)
    reader, writer = await asyncio.wait_for(fut, timeout=timeout)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return time.perf_counter() - start


async def run_probe(t: Dict, timeout: float):
    url = t["url"].strip()
    name = t.get("name", url)
    threshold = float(t.get("threshold_seconds", 1.0))

    if url.startswith("http://") or url.startswith("https://"):
        scheme = "http"
        target_label = url
        try:
            latency = await probe_http(url, timeout)
            LATENCY.labels(name, scheme, target_label).set(latency)
            THRESH.labels(name, scheme, target_label).set(threshold)
            UP.labels(name, scheme, target_label).set(1)
        except Exception:
            ERRORS.labels(name, scheme, target_label).inc()
            UP.labels(name, scheme, target_label).set(0)
    elif url.startswith("tcp://"):
        scheme = "tcp"
        host_port = url[6:]
        if ":" not in host_port:
            raise ValueError("tcp:// requires host:port")
        host, port = host_port.split(":", 1)
        port = int(port)
        target_label = f"{host}:{port}"
        try:
            latency = await probe_tcp(host, port, timeout)
            LATENCY.labels(name, scheme, target_label).set(latency)
            THRESH.labels(name, scheme, target_label).set(threshold)
            UP.labels(name, scheme, target_label).set(1)
        except Exception:
            ERRORS.labels(name, scheme, target_label).inc()
            UP.labels(name, scheme, target_label).set(0)
    else:
        raise ValueError("Unsupported URL scheme. Use http(s):// or tcp://")
    

async def scheduler():
    await asyncio.sleep(0.2)
    while True:
        try:
            targets, interval, timeout = load_config(TARGETS_FILE)
            state["targets"], state["interval"], state["timeout"] = targets, interval, timeout
        except Exception:
            # Keep previous config if reload fails
            targets = state["targets"]
            interval = state["interval"]
            timeout = state["timeout"]

        if not targets:
            await asyncio.sleep(interval)
            continue

        tasks = [run_probe(t, timeout) for t in targets]
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(interval)

@app.on_event("startup")
async def _startup():
    asyncio.create_task(scheduler())

@app.get("/health")
async def health():
    return {"ok": True, "targets": len(state["targets"])}


@app.get("/metrics")
async def metrics():
    data = generate_latest(REGISTRY)
    return PlainTextResponse(data, media_type=CONTENT_TYPE_LATEST)

@app.post("/alert")
async def alert_webhook(req: Request):
    payload = await req.json()
    # Minimal logging; in real life forward to Slack/Email/Webhook
    print("\n=== ALERT RECEIVED ===\n", payload)
    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)