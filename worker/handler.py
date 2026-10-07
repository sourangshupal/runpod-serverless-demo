"""RunPod Serverless worker: FLUX.1-schnell text-to-image.

The model is loaded once per worker boot (module level) — that load is the
cold start the demo measures. Uses optimum-quanto fp8 storage quantization
so schnell fits comfortably on 24GB GPUs (A5000/3090/4090), computing in bf16.
HF cache lives on the network volume (HF_HOME) so cold starts after the
first are disk-loads, not 23GB downloads.
"""

import base64
import io
import os
import time

import runpod
import torch
from diffusers import FluxPipeline, FluxTransformer2DModel
from optimum.quanto import freeze, qfloat8, quantize

MODEL_ID = os.getenv("MODEL_ID", "black-forest-labs/FLUX.1-schnell")

print(f"[worker] loading {MODEL_ID} ...", flush=True)
t0 = time.time()

transformer = FluxTransformer2DModel.from_pretrained(
    MODEL_ID, subfolder="transformer", torch_dtype=torch.bfloat16
)
quantize(transformer, qfloat8)  # fp8 storage, bf16 compute
freeze(transformer)

pipe = FluxPipeline.from_pretrained(
    MODEL_ID, transformer=transformer, torch_dtype=torch.bfloat16
)
pipe.enable_model_cpu_offload()  # fits 24GB VRAM

print(f"[worker] ready in {time.time() - t0:.1f}s", flush=True)


def handler(event):
    inp = event.get("input", {})
    prompt = inp["prompt"]
    width = int(inp.get("width", 1024))
    height = int(inp.get("height", 1024))
    steps = int(inp.get("steps", 4))  # schnell is designed for 4 steps
    seed = int(inp.get("seed", 0))

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
