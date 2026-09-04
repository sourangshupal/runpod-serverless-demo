# /// script
# requires-python = ">=3.12"
# dependencies = ["nbformat==5.11.1"]
# ///
"""Build notebooks/runpod_serverless_demo.ipynb (not executed here)."""

from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
md = lambda s: nbf.v4.new_markdown_cell(s)  # noqa: E731
code = lambda s: nbf.v4.new_code_cell(s)  # noqa: E731

nb.cells = [
    md(
        "# RunPod Serverless, From Zero to a Production API\n"
        "\n"
        "The notebook behind the demo: sign up → API key → **this notebook** → "
        "pay-per-second GPU inference.\n"
        "\n"
        "What we prove, in order:\n"
        "1. An idle endpoint keeps **zero workers** — nothing to pay when nothing runs\n"
        "2. The **first request from zero** (cold start: queue + worker spin-up)\n"
        "3. A **warm request** — the same call once a worker is active\n"
        "4. A **burst** of concurrent requests — the queue absorbing load\n"
        "5. **The bill** — what this whole session actually cost"
    ),
    md(
        "## 1. Setup\n"
        "\n"
        "Config lives in `.env` (`RUNPOD_API_KEY`, `ENDPOINT_ID`, `GPU_HOURLY_USD`).\n"
        "The endpoint can be one you deployed yourself (any Hub template) or a "
        "Runpod-hosted public model endpoint — the API is identical.\n"
        "\n"
        "If you need to create your own endpoint first:\n"
        "`uv run scripts/create_endpoint.py --template-id <HUB_TEMPLATE_ID>`"
    ),
    code(
        "import json\n"
        "import os\n"
        "import time\n"
        "\n"
        "import httpx\n"
        "from dotenv import load_dotenv\n"
        "\n"
        "load_dotenv('../.env')  # adjust to '../.env' if run from notebooks/\n"
        "\n"
        "API_KEY = os.environ['RUNPOD_API_KEY']\n"
        "ENDPOINT_ID = os.environ['ENDPOINT_ID']\n"
        "GPU_HOURLY_USD = float(os.getenv('GPU_HOURLY_USD', '0.69'))\n"
        "\n"
        "BASE_URL = f'https://api.runpod.ai/v2/{ENDPOINT_ID}'\n"
        "HEADERS = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}\n"
        "PROMPT = 'A small red cube on a white background'\n"
        "print(f'Endpoint: {BASE_URL}')"
    ),
    md(
        "## 2. Health check — how many workers are running right now?\n"
        "\n"
        "Min workers = 0 means the endpoint **scales to zero** when idle — "
        "this check is where we confirm there's nothing running and nothing to pay for.\n"
        "\n"
        "(Public model endpoints don't expose `/health`; your own endpoints do.)"
    ),
    code(
        "with httpx.Client(timeout=30.0) as client:\n"
        "    resp = client.get(f'{BASE_URL}/health', headers=HEADERS)\n"
        "\n"
        "if resp.status_code == 401:\n"
        "    print('/health not available on this endpoint (normal for public model endpoints).')\n"
        "else:\n"
        "    resp.raise_for_status()\n"
        "    print(json.dumps(resp.json(), indent=2))"
    ),
    md(
        "## 3. Cold start — the first request from zero workers\n"
        "\n"
        "Submit an async job (`POST /run`), then poll `GET /status/{id}`. "
        "The first call pays the cold start: worker provisioning + model load. "
        "`delayTime` in the response is exactly that cost, in milliseconds."
    ),
    code(
        "with httpx.Client() as client:\n"
        "    t0 = time.monotonic()\n"
        "    resp = client.post(\n"
        "        f'{BASE_URL}/run', headers=HEADERS,\n"
        "        json={'input': {'prompt': PROMPT}}, timeout=30.0,\n"
        "    )\n"
        "    resp.raise_for_status()\n"
        "    job_id = resp.json()['id']\n"
        "    print(f'job submitted: {job_id}')\n"
        "\n"
        "    last = None\n"
        "    while True:\n"
        "        job = client.get(f'{BASE_URL}/status/{job_id}', headers=HEADERS, timeout=30.0).json()\n"
        "        if job['status'] != last:\n"
        "            print(f\"t={time.monotonic() - t0:6.1f}s  status -> {job['status']}\")\n"
        "            last = job['status']\n"
        "        if job['status'] == 'COMPLETED':\n"
        "            cold = job\n"
        "            break\n"
        "        assert job['status'] not in ('FAILED', 'CANCELLED'), job\n"
        "        time.sleep(2)\n"
        "\n"
        "print(f\"cold start delayTime: {cold['delayTime']} ms, executionTime: {cold['executionTime']} ms\")"
    ),
    md(
        "## 4. Warm request — the FlashBoot difference\n"
        "\n"
        "Same call, immediately after, via `/runsync` (synchronous — waits for the result). "
        "With a worker already active and FlashBoot enabled, `delayTime` should collapse "
        "from seconds to milliseconds."
    ),
    code(
        "with httpx.Client() as client:\n"
        "    t0 = time.monotonic()\n"
        "    resp = client.post(\n"
        "        f'{BASE_URL}/runsync?wait=120000', headers=HEADERS,\n"
        "        json={'input': {'prompt': PROMPT}}, timeout=150.0,\n"
        "    )\n"
        "    resp.raise_for_status()\n"
        "    warm = resp.json()\n"
        "    warm_wall = time.monotonic() - t0\n"
        "\n"
        "print(f\"warm delayTime:    {warm['delayTime']:>6} ms\")\n"
        "print(f\"cold delayTime:    {cold['delayTime']:>6} ms\")\n"
        "print(f\"difference:        {cold['delayTime'] - warm['delayTime']:>6} ms faster when warm\")\n"
        "print()\n"
        "print('Output:', json.dumps(warm['output'])[:300])"
    ),
    md(
        "## 5. Burst — 20 concurrent requests\n"
        "\n"
        "Fire 20 requests at once and watch how the platform absorbs them: "
        "each lands in the queue, workers pick jobs up as they scale, "
        "and every request still completes."
    ),
    code(
        "import asyncio\n"
        "\n"
        "TOPICS = [\n"
        "    'GPU virtualization', 'quantization of LLMs', 'KV caching', 'speculative decoding',\n"
        "    'LoRA adapters', 'mixture-of-experts', 'flash attention', 'gradient checkpointing',\n"
        "    'RAG pipelines', 'vector databases', 'RLHF', 'distillation',\n"
        "    'batch inference', 'CUDA streams', 'tensor parallelism', 'pipeline parallelism',\n"
        "    'activation checkpointing', 'model sharding', 'token healing', 'continuous batching',\n"
        "]\n"
        "\n"
        "async def one(client, prompt):\n"
        "    t = time.monotonic()\n"
        "    r = await client.post(\n"
        "        f'{BASE_URL}/runsync?wait=300000', headers=HEADERS,\n"
        "        json={'input': {'prompt': prompt}}, timeout=320.0,\n"
        "    )\n"
        "    r.raise_for_status()\n"
        "    job = r.json()\n"
        "    job['_wall_s'] = time.monotonic() - t\n"
        "    return job\n"
        "\n"
        "t0 = time.monotonic()\n"
        "async with httpx.AsyncClient() as client:\n"
        "    results = await asyncio.gather(*(one(client, f'An icon of {t}') for t in TOPICS))\n"
        "burst_wall = time.monotonic() - t0\n"
        "\n"
        "completed = [j for j in results if j['status'] == 'COMPLETED']\n"
        "walls = sorted(j['_wall_s'] for j in completed)\n"
        "delays = sorted(j['delayTime'] for j in completed)\n"
        "print(f'completed:            {len(completed)} / {len(results)}')\n"
        "print(f'burst wall time:      {burst_wall:.1f}s')\n"
        "print(f'request wall median:  {walls[len(walls)//2]:.1f}s   max: {walls[-1]:.1f}s')\n"
        "print(f'delayTime median:     {delays[len(delays)//2]} ms')"
    ),
    md(
        "## 6. The bill\n"
        "\n"
        "Per-second billing, from worker start to full stop. "
        "Some endpoints report the exact billed cost per job in the output — "
        "when they don't, we estimate from worker time × the GPU's hourly rate."
    ),
    code(
        "jobs = [cold, warm] + results\n"
        "\n"
        "reported = [\n"
        "    j['output']['cost'] for j in jobs\n"
        "    if isinstance(j.get('output'), dict) and j['output'].get('cost') is not None\n"
        "]\n"
        "if reported:\n"
        "    print(f'Billed cost reported by the endpoint: ${sum(reported):.5f}')\n"
        "else:\n"
        "    worker_s = sum(j.get('delayTime', 0) + j.get('executionTime', 0) for j in jobs) / 1000.0\n"
        "    print(f'Worker time: {worker_s:.1f}s at ${GPU_HOURLY_USD}/hr '\n"
        "          f'= ${worker_s * GPU_HOURLY_USD / 3600.0:.5f}')\n"
        "print()\n"
        "print('That is the entire economics of the demo: a real GPU, real concurrency, pennies.')"
    ),
    md(
        "## Wrap-up\n"
        "\n"
        "**Runpod is the AI Developer Cloud. Sign Up Today.** — link in the video description.\n"
        "\n"
        "Reproduce this end to end:\n"
        "1. Sign up and create an API key (console → Settings → API Keys — use a *Restricted* key)\n"
        "2. Deploy an endpoint: console → Serverless → New Endpoint, or `scripts/create_endpoint.py`\n"
        "3. Put the key and endpoint ID in `.env`\n"
        "4. Run this notebook top to bottom"
    ),
]

out = Path(__file__).resolve().parent.parent / "notebooks" / "runpod_serverless_demo.ipynb"
out.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, str(out))
print(f"wrote {out}")
