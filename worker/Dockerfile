FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

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
