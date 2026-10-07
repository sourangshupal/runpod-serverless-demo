"""RunPod Serverless worker: FLUX.1-schnell text-to-image.

Design notes (learned from the first version):
- runpod.serverless.start() must run immediately — RunPod kills containers
  that don't handshake within its provisioning window. The model is therefore
  loaded lazily on the first request (that load IS the cold start).
- bf16 weights (~24GB) need a >=32GB GPU, so the endpoint is configured with
  32/48GB GPU types in priority order. No fp8 quantization needed there,
  which also makes the load faster.
"""

import base64
import io
import threading
import time

import runpod
import torch
from diffusers import FluxPipeline

MODEL_ID = "black-forest-labs/FLUX.1-schnell"

_pipe = None
_lock = threading.Lock()


def get_pipe():
    global _pipe
    with _lock:
        if _pipe is None:
            print(f"[worker] loading {MODEL_ID} ...", flush=True)
            t0 = time.time()
            _pipe = FluxPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
            _pipe.to("cuda")
            print(f"[worker] ready in {time.time() - t0:.1f}s", flush=True)
    return _pipe


def handler(event):
    inp = event.get("input", {})
    prompt = inp["prompt"]
    width = int(inp.get("width", 1024))
    height = int(inp.get("height", 1024))
    steps = int(inp.get("steps", 4))  # schnell is designed for 4 steps
    seed = int(inp.get("seed", 0))

    pipe = get_pipe()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    image = pipe(
        prompt=prompt,
        width=width,
        height=height,
        num_inference_steps=steps,
        guidance_scale=0.0,  # schnell: CFG-distilled, 0 is correct
        generator=generator,
    ).images[0]

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"image": encoded, "seed": seed, "steps": steps, "width": width, "height": height}


runpod.serverless.start({"handler": handler})
