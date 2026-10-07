FROM runpod/pytorch:2.4.0-py3.11-cuda12.1.1-devel-ubuntu22.04

WORKDIR /

RUN pip install --no-cache-dir \
    runpod==1.12.0 \
    diffusers==0.36.0 \
    transformers==4.56.2 \
    accelerate==1.10.1 \
    optimum-quanto==0.2.7 \
    safetensors==0.6.2 \
    sentencepiece==0.2.1

COPY handler.py /

CMD ["python", "-u", "handler.py"]
