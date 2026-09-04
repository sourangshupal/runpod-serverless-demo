# RunPod Serverless Demo

Codebase for the RunPod Serverless walkthrough (sponsored YouTube video, brief #9798).
It proves the story end to end: **sign up → deploy an endpoint → send traffic → pay per second.**

## What's here

| Path | Purpose | Video segment |
|---|---|---|
| `scripts/create_endpoint.py` | Create a Serverless endpoint via the REST API (`POST /v1/endpoints`) | 13:30–14:30 |
| `scripts/smoke_test.py` | Health check → cold start (`/run` + poll) → warm request (`/runsync`) with delayTime comparison and cost estimate | 14:30–15:30 |
| `scripts/burst_test.py` | 20 concurrent requests while sampling `/health` — watch workers scale in real time | 15:30–16:30 |
| `notebooks/runpod_serverless_demo.ipynb` | Final narrated notebook for the on-camera walkthrough | full demo |
| `scripts/build_notebook.py` | Regenerates the notebook from source | — |
| `.env.example` | Config template | — |

Sign-up happens in the Runpod console on camera; the endpoint can then be deployed
**either** on camera via Serverless → New Endpoint **or** with `create_endpoint.py` —
whichever reads better on video.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
```

Fill in `.env`:

- `RUNPOD_API_KEY` — create in the RunPod console: **Settings → API Keys → Create API Key**.
  Use a **Restricted** key scoped to this endpoint only (least privilege).
- `ENDPOINT_ID` — the ID of your Serverless endpoint (deploy from a Hub template, e.g. a
  vLLM text-generation worker; enable FlashBoot, set min workers to 0).
- `GPU_HOURLY_USD` — the hourly rate of your endpoint's GPU tier (see
  [serverless pricing](https://www.runpod.io/pricing)); used only for the cost estimate printout.

## Run

```bash
uv run scripts/create_endpoint.py --template-id <HUB_TEMPLATE_ID>   # optional: deploy via API
uv run scripts/smoke_test.py                    # single-request proof, cold vs warm
uv run scripts/burst_test.py                    # 20 concurrent requests + scaling watch
uv run scripts/burst_test.py --requests 40 --concurrency 20
```

`ENDPOINT_ID` can be any queue-based endpoint you deployed, **or** a Runpod-hosted
[public model endpoint](https://docs.runpod.io/overview) (e.g. `black-forest-labs-flux-1-schnell`)
for zero-setup testing — the API is identical. Public endpoints don't expose `/health`;
your own endpoints do.

To watch the notebook: `uv run jupyter notebook` (or `jupyter lab`), open
`notebooks/runpod_serverless_demo.ipynb`.

## Notes

- **Cold start can take minutes** (container image pull + model load). The smoke test's
  first request uses `/run` + status polling with a 10-minute budget — this is normal.
  Steady-state requests use `/runsync`.
- `delayTime` in the API response = time spent queued + starting a worker (the cold-start
  evidence); `executionTime` = actual GPU work.
- When an endpoint reports a per-job `cost` in its output, the scripts print that as the
  authoritative billed cost; otherwise they estimate from worker time × GPU hourly rate.
- Endpoint *creation* is available both ways: on camera in the console, or scripted via
  `scripts/create_endpoint.py` (needs a Hub template ID).
