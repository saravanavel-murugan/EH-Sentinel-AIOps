# EventHub Ops Sentinel — Phase 8 packaging artefact.
#
# A minimal, reproducible image that runs the Streamlit operator console. It is
# offline-first: SENTINEL_LLM defaults to the deterministic fake provider, so the
# container starts and is usable with NO API key and NO network.
#
# Secrets are NEVER baked into the image. To run the live OpenAI path, inject the
# key at runtime (see the run example below) — do not add OPENAI_API_KEY here and
# do not COPY the local .env (it is excluded via .dockerignore).
#
# Build:
#   docker build -t eventhub-sentinel .
#
# Run (offline fake provider, default):
#   docker run --rm -p 8501:8501 eventhub-sentinel
#
# Run (live OpenAI path, key injected at runtime — never baked in):
#   docker run --rm -p 8501:8501 \
#     -e SENTINEL_LLM=openai -e SENTINEL_EMBEDDINGS=openai \
#     -e OPENAI_API_KEY=... eventhub-sentinel

FROM python:3.11-slim

# Keep Python output unbuffered and skip .pyc files in the image layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install pinned dependencies first so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the project source (the .dockerignore keeps .env, caches and logs out).
COPY . .

# Offline-first defaults. $PORT is configurable at runtime.
ENV SENTINEL_LLM=fake \
    SENTINEL_EMBEDDINGS=fake \
    SENTINEL_LOG_LEVEL=INFO \
    PORT=8501

EXPOSE 8501

# Run the Streamlit operator console, bound to all interfaces, headless.
CMD streamlit run ui/streamlit_app.py \
    --server.address=0.0.0.0 \
    --server.port=${PORT} \
    --server.headless=true
