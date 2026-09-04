"""Create a RunPod Serverless endpoint via the REST API.

Wraps POST https://rest.runpod.io/v1/endpoints — the same operation as
Serverless -> New Endpoint in the console.

You need a templateId: open a worker in the Runpod Hub (console -> Hub),
choose a template (e.g. a vLLM text-generation worker), and copy the
template ID from its deploy URL / page.

Usage:
    uv run scripts/create_endpoint.py --template-id 30zmvf89kd
    uv run scripts/create_endpoint.py --template-id 30zmvf89kd --name video-demo \
        --gpu "NVIDIA GeForce RTX 4090" --max-workers 5

After creation, put the printed endpoint ID into .env (ENDPOINT_ID=...).
"""

import argparse
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os  # noqa: E402

API_KEY = os.getenv("RUNPOD_API_KEY")
REST_URL = "https://rest.runpod.io/v1/endpoints"
console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-id", required=True, help="Hub template ID to deploy from")
    parser.add_argument("--name", default="runpod-demo-endpoint")
    parser.add_argument(
        "--gpu",
        action="append",
        dest="gpus",
        help="GPU type; repeat for priority order (fallbacks). Default: 4090 -> A5000 -> 3090 (24GB class)",
    )
    parser.add_argument("--min-workers", type=int, default=0, help="0 = scales to zero when idle")
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--idle-timeout", type=int, default=5, help="seconds before an idle worker stops")
    parser.add_argument("--execution-timeout", type=int, default=600, help="max job runtime (seconds)")
    return parser.parse_args()


def main() -> None:
    if not API_KEY:
        console.print("[bold red]Missing RUNPOD_API_KEY.[/] Set it in .env first.")
        sys.exit(1)

    args = parse_args()
    gpu_types = args.gpus or [
        "NVIDIA GeForce RTX 4090",
        "NVIDIA RTX A5000",
        "NVIDIA GeForce RTX 3090",
    ]
    payload = {
        "name": args.name,
        "templateId": args.template_id,
        "computeType": "GPU",
        "gpuCount": 1,
        "gpuTypeIds": gpu_types,
        "workersMin": args.min_workers,
        "workersMax": args.max_workers,
        "idleTimeout": args.idle_timeout,
        "executionTimeoutMs": args.execution_timeout * 1000,
        "scalerType": "QUEUE_DELAY",
        "scalerValue": 4,
    }
    console.print(f"Creating endpoint '{args.name}' from template {args.template_id} ...")
    console.print(f"  GPUs (priority order): {', '.join(gpu_types)}")
    console.print(f"  workers: {args.min_workers}..{args.max_workers}, idle timeout {args.idle_timeout}s")

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(REST_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json=payload)

    if resp.status_code >= 400:
        console.print(f"[bold red]Creation failed ({resp.status_code}):[/] {resp.text}")
        sys.exit(1)

    endpoint = resp.json()
    endpoint_id = endpoint.get("id")
    console.print(f"[green]Endpoint created.[/] id = [bold]{endpoint_id}[/]")
    console.print("Next: set ENDPOINT_ID in .env, then run scripts/smoke_test.py")


if __name__ == "__main__":
    main()
