FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

# The AI model (~15 GB) is not part of the image: it is downloaded on the first start into
# /data/hf (a volume), using HF_TOKEN from the compose file.
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    OUTPUT_DIR=/data/outputs

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
