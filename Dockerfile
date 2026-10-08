# syntax=docker/dockerfile:1
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

# Which transformer quantisation to bake in (Q5_K_S ≈ 8.3 GB, Q4_K_S ≈ 6.8 GB for tight VRAM).
ARG FLUX_GGUF_FILE=flux1-fill-dev-Q5_K_S.gguf

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    FLUX_GGUF_FILE=${FLUX_GGUF_FILE} \
    OUTPUT_DIR=/data/outputs

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Models (~15 GB) in their own layer before the code, so code changes do not download them again.
# The Hugging Face token comes in as a build secret (.env) and is not stored in the image.
COPY app/__init__.py app/models.py ./app/
RUN --mount=type=secret,id=hf_env python -m app.models /run/secrets/hf_env
ENV HF_HUB_OFFLINE=1

COPY app ./app
COPY templates ./templates

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
