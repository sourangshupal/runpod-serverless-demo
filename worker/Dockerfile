FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

WORKDIR /

RUN pip install --no-cache-dir \
    runpod==1.12.0 \
    diffusers==0.36.0 \
    transformers==4.56.2 \
    accelerate==1.10.1 \
    optimum-quanto==0.2.7 \
    safetensors==0.6.2 \
    sentencepiece==0.2.1 \
    "huggingface_hub[cli]==0.36.0"

# Bake the model into the image at build time (token via BuildKit secret —
# it never lands in a layer or the image history). At runtime the worker
# loads from this cache with no network and no HF_TOKEN needed.
RUN --mount=type=secret,id=hf_token \
    HF_HOME=/model-cache HF_TOKEN=$(cat /run/secrets/hf_token) \
    huggingface-cli download black-forest-labs/FLUX.1-schnell --exclude "*.md"

ENV HF_HOME=/model-cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY handler.py /

CMD ["python", "-u", "handler.py"]
