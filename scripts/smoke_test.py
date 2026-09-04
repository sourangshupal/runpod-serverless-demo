"""Smoke test for a RunPod Serverless endpoint.

Verifies, in order:
1. /health        - worker/queue state (expect 0 workers on an idle endpoint)
2. Cold start     - /run + poll /status until COMPLETED (first request from zero workers)
3. Warm request   - /runsync immediately after (the FlashBoot comparison moment)

Usage:
    uv run scripts/smoke_test.py
"""

import json
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os  # noqa: E402

API_KEY = os.getenv("RUNPOD_API_KEY")
ENDPOINT_ID = os.getenv("ENDPOINT_ID")
GPU_HOURLY_USD = float(os.getenv("GPU_HOURLY_USD", "0.69"))

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
PROMPT = "Explain GPU virtualization in one sentence."
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 600.0  # cold start = image pull + model load; can take minutes

console = Console()

if not API_KEY or not ENDPOINT_ID:
    console.print(
        "[bold red]Missing configuration.[/] Copy .env.example to .env and set "
        "RUNPOD_API_KEY and ENDPOINT_ID. "
        "Create a Restricted key: Runpod console -> Settings -> API Keys."
    )
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def health(client: httpx.Client) -> dict | None:
    resp = client.get(f"{BASE_URL}/health", headers=HEADERS)
    if resp.status_code == 401:
        return None  # public model endpoints don't expose /health — own endpoints do
    resp.raise_for_status()
    return resp.json()


def show_health(label: str, h: dict | None) -> None:
    if h is None:
        console.print(
            "[yellow]/health unavailable for this endpoint[/] "
            "(expected for Runpod-hosted public model endpoints; "
            "your own endpoints report worker counts here)."
        )
        return
    table = Table(title=f"/health — {label}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    workers = h.get("workers", {})
    jobs = h.get("jobs", {})
    table.add_row("workers running", str(workers.get("running", 0)))
    table.add_row("workers idle", str(workers.get("idle", 0)))
    table.add_row("jobs in queue", str(jobs.get("inQueue", 0)))
    table.add_row("jobs in progress", str(jobs.get("inProgress", 0)))
    table.add_row("jobs completed", str(jobs.get("completed", 0)))
    table.add_row("jobs failed", str(jobs.get("failed", 0)))
    console.print(table)


def cold_start(client: httpx.Client) -> dict:
    """Submit an async job and poll /status until COMPLETED."""
    console.rule("[bold]Cold start: first request from zero workers[/]")
    console.print("Submitting async job via /run ...")
    submitted = time.monotonic()
    resp = client.post(
        f"{BASE_URL}/run",
        headers=HEADERS,
        json={"input": {"prompt": PROMPT}},
        timeout=30.0,
    )
    resp.raise_for_status()
    job_id = resp.json()["id"]
    console.print(f"Job ID: {job_id}")

    last_status = None
    while True:
        elapsed = time.monotonic() - submitted
        if elapsed > POLL_TIMEOUT:
            console.print(f"[bold red]Timed out after {POLL_TIMEOUT:.0f}s.[/]")
            sys.exit(1)
        status_resp = client.get(
            f"{BASE_URL}/status/{job_id}", headers=HEADERS, timeout=30.0
        )
        status_resp.raise_for_status()
        job = status_resp.json()
        if job["status"] != last_status:
            console.print(f"  t={elapsed:6.1f}s  status -> [bold]{job['status']}[/]")
            last_status = job["status"]
        if job["status"] == "COMPLETED":
            wall_time = time.monotonic() - submitted
            console.print(f"[green]Completed in {wall_time:.1f}s wall time.[/]")
            job["_wall_time_s"] = wall_time
            return job
        if job["status"] in ("FAILED", "ERROR", "CANCELLED"):
            console.print(f"[bold red]Job {job['status']}: {json.dumps(job, indent=2)}[/]")
            sys.exit(1)
        time.sleep(POLL_INTERVAL)


def warm_request(client: httpx.Client) -> dict:
    console.rule("[bold]Warm request: /runsync against an active worker[/]")
    started = time.monotonic()
    resp = client.post(
        f"{BASE_URL}/runsync?wait=120000",
        headers=HEADERS,
        json={"input": {"prompt": PROMPT}},
        timeout=150.0,
    )
    resp.raise_for_status()
    job = resp.json()
    job["_wall_time_s"] = time.monotonic() - started
    return job


def show_output(job: dict) -> None:
    output = job.get("output")
    text = json.dumps(output, indent=2) if not isinstance(output, str) else output
    console.print(Panel(text.strip()[:2000] or "(empty output)", title="Model output"))


def show_comparison(cold: dict, warm: dict) -> None:
    table = Table(title="Cold vs warm — delayTime is queue + cold start (ms)")
    table.add_column("Run", style="cyan")
    table.add_column("delayTime (ms)", justify="right")
    table.add_column("executionTime (ms)", justify="right")
    table.add_column("wall time (s)", justify="right")
    table.add_row("cold", str(cold.get("delayTime")), str(cold.get("executionTime")), f"{cold['_wall_time_s']:.1f}")
    table.add_row("warm", str(warm.get("delayTime")), str(warm.get("executionTime")), f"{warm['_wall_time_s']:.1f}")
    console.print(table)

    cold_delay = cold.get("delayTime") or 0
    warm_delay = warm.get("delayTime") or 0
    if cold_delay > warm_delay:
        console.print(
            f"[green]Warm request answered {cold_delay - warm_delay} ms sooner "
            "— no cold start on an active worker.[/]"
        )


def show_cost(*jobs: dict) -> None:
    billed = [j["output"].get("cost") for j in jobs
              if isinstance(j.get("output"), dict) and j["output"].get("cost") is not None]
    if billed:
        console.print(
            f"[bold]Billed cost (reported by the endpoint):[/] [bold green]${sum(billed):.5f}[/]"
        )
    total_ms = sum((j.get("delayTime") or 0) + (j.get("executionTime") or 0) for j in jobs)
    total_s = total_ms / 1000.0
    cost = total_s * GPU_HOURLY_USD / 3600.0
    console.print(
        f"[bold]Estimated bill for this smoke test:[/] {total_s:.1f}s of worker time "
        f"at ${GPU_HOURLY_USD}/hr = [bold green]${cost:.5f}[/]"
    )


def main() -> None:
    with httpx.Client() as client:
        console.rule("[bold]1. Health check — idle endpoint should show 0 workers[/]")
        show_health("before any request", health(client))

        cold = cold_start(client)
        show_output(cold)

        warm = warm_request(client)
        show_output(warm)

        show_comparison(cold, warm)
        show_cost(cold, warm)

        show_health("after requests", health(client))


if __name__ == "__main__":
    main()
