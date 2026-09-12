FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependencies first so this layer is cached unless pyproject.toml/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

COPY config/ ./config/
COPY src/ ./src/
COPY main.py ./

ENV PATH="/app/.venv/bin:${PATH}"

# GCP credentials are provided at runtime (mounted service-account key via
# GOOGLE_APPLICATION_CREDENTIALS, or workload identity) — not baked into the image.
CMD ["python", "main.py"]
