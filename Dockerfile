# Stage 1: Build React frontend
FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY kith/ kith/
RUN pip install --no-cache-dir -e .

# Copy built frontend into backend static dir
COPY --from=frontend-build /frontend/dist /app/static

ENV KITH_DATA_DIR=/data/kith
VOLUME ["/data/kith"]

# Pre-create symlink target so ChromaDB ONNX model persists across restarts
RUN mkdir -p /data/kith/onnx_cache/onnx_models \
    && mkdir -p /root/.cache/chroma \
    && ln -sf /data/kith/onnx_cache/onnx_models /root/.cache/chroma/onnx_models

EXPOSE 8000

CMD ["uvicorn", "kith.main:app", "--host", "0.0.0.0", "--port", "8000"]
