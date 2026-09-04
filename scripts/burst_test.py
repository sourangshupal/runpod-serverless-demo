"""Burst test for a RunPod Serverless endpoint.

Fires N concurrent /runsync requests and, while they run, samples /health
once per second to capture the worker pool scaling up.

Usage:
    uv run scripts/burst_test.py
    uv run scripts/burst_test.py --requests 40 --concurrency 20
"""

import argparse
import asyncio
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os  # noqa: E402

API_KEY = os.getenv("RUNPOD_API_KEY")
ENDPOINT_ID = os.getenv("ENDPOINT_ID")
GPU_HOURLY_USD = float(os.getenv("GPU_HOURLY_USD", "0.69"))

BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
TOPICS = [
    "GPU virtualization", "quantization of LLMs", "KV caching", "speculative decoding",
    "LoRA adapters", "mixture-of-experts", "flash attention", "gradient checkpointing",
    "RAG pipelines", "vector databases", "RLHF", "distillation",
    "batch inference", "CUDA streams", "tensor parallelism", "pipeline parallelism",
    "activation checkpointing", "model sharding", "token healing", "continuous batching",
]

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=20)
    return parser.parse_args()


async def one_request(client: httpx.AsyncClient, prompt: str) -> dict:
    started = time.monotonic()
    try:
        resp = await client.post(
            f"{BASE_URL}/runsync?wait=300000",
            headers=HEADERS,
            json={"input": {"prompt": prompt}},
            timeout=httpx.Timeout(320.0, connect=10.0),
        )
        resp.raise_for_status()
        job = resp.json()
    except Exception as exc:  # noqa: BLE001 - report per-request failures in the table
        return {"prompt": prompt, "status": f"ERROR: {exc.__class__.__name__}", "_wall_s": time.monotonic() - started}
    job["prompt"] = prompt
    job["_wall_s"] = time.monotonic() - started
    return job


async def watch_health(client: httpx.AsyncClient, samples: list, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            resp = await client.get(f"{BASE_URL}/health", headers=HEADERS, timeout=10.0)
            h = resp.json()
            samples.append(
                (
                    time.monotonic(),
                    h.get("workers", {}).get("running", 0),
                    h.get("workers", {}).get("idle", 0),
                    h.get("jobs", {}).get("inQueue", 0),
                    h.get("jobs", {}).get("inProgress", 0),
                )
            )
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1.0)


async def run_burst(n_requests: int, concurrency: int) -> None:
    prompts = [
        f"Explain {TOPICS[i % len(TOPICS)]} to a junior ML engineer in two sentences."
        for i in range(n_requests)
    ]
    samples: list = []
    stop = asyncio.Event()
    t0 = time.monotonic()

    async with httpx.AsyncClient() as client:
        watcher = asyncio.create_task(watch_health(client, samples, stop))
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded(prompt: str) -> dict:
            async with semaphore:
                return await one_request(client, prompt)

        console.print(
            f"Firing {n_requests} requests (concurrency={concurrency}) at {BASE_URL} ..."
        )
        results = await asyncio.gather(*(bounded(p) for p in prompts))
        stop.set()
        await watcher

    total_wall = time.monotonic() - t0

    table = Table(title=f"Per-request results ({n_requests} requests)")
    table.add_column("#", justify="right", style="dim")
    table.add_column("status")
    table.add_column("delayTime (ms)", justify="right")
    table.add_column("executionTime (ms)", justify="right")
    table.add_column("wall (s)", justify="right")
    for i, job in enumerate(results, 1):
        style = "green" if job.get("status") == "COMPLETED" else "red"
        table.add_row(
            str(i),
            f"[{style}]{job.get('status')}[/]",
            str(job.get("delayTime", "-")),
            str(job.get("executionTime", "-")),
            f"{job['_wall_s']:.1f}",
        )
    console.print(table)

    completed = [j for j in results if j.get("status") == "COMPLETED"]
    walls = sorted(j["_wall_s"] for j in completed)
    delays = sorted((j.get("delayTime") or 0) for j in completed)
    summary = Table(title="Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("completed", f"{len(completed)} / {n_requests}")
    if walls:
        summary.add_row("wall time (median / max)", f"{walls[len(walls)//2]:.1f}s / {walls[-1]:.1f}s")
        summary.add_row("total wall time for burst", f"{total_wall:.1f}s")
    if delays:
        summary.add_row("delayTime median (ms)", str(delays[len(delays) // 2]))
    console.print(summary)

    if samples:
        t_base = samples[0][0]
        timeline = Table(title="Worker scaling, sampled from /health every 1s")
        timeline.add_column("t (s)", justify="right", style="dim")
        timeline.add_column("workers running", justify="right")
        timeline.add_column("workers idle", justify="right")
        timeline.add_column("in queue", justify="right")
        timeline.add_column("in progress", justify="right")
        for t, running, idle, queued, progress in samples:
            timeline.add_row(f"{t - t_base:5.1f}", str(running), str(idle), str(queued), str(progress))
        console.print(timeline)
        max_workers = max(s[1] + s[2] for s in samples)
        console.print(f"[bold]Peak workers observed:[/] {max_workers}")
    else:
        console.print(
            "[yellow]/health unavailable for this endpoint[/] "
            "(expected for Runpod-hosted public model endpoints; "
            "your own endpoints show worker scaling here)."
        )

    if completed:
        billed = [j["output"].get("cost") for j in completed
                  if isinstance(j.get("output"), dict) and j["output"].get("cost") is not None]
        if billed:
            console.print(
                f"[bold]Billed cost (reported by the endpoint):[/] [bold green]${sum(billed):.5f}[/]"
            )
        total_ms = sum((j.get("delayTime") or 0) + (j.get("executionTime") or 0) for j in completed)
        cost = (total_ms / 1000.0) * GPU_HOURLY_USD / 3600.0
        console.print(
            f"[bold]Estimated bill for the burst:[/] {total_ms/1000.0:.1f}s of worker time "
            f"at ${GPU_HOURLY_USD}/hr = [bold green]${cost:.5f}[/]"
        )


def main() -> None:
    if not API_KEY or not ENDPOINT_ID:
        console.print(
            "[bold red]Missing configuration.[/] Copy .env.example to .env and set "
            "RUNPOD_API_KEY and ENDPOINT_ID."
        )
        raise SystemExit(1)
    args = parse_args()
    asyncio.run(run_burst(args.requests, args.concurrency))


if __name__ == "__main__":
    main()
