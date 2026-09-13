# Backend image for Railway. Only the API and its dependencies ship here —
# the CSV pipeline in scripts/ and data_clean/ runs locally against the same
# Neo4j instance, so it is deliberately excluded (see .dockerignore).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && pip install ".[api]"

# Railway injects PORT at runtime; 8000 is the local-run fallback.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn med_graph.api.app:app --host 0.0.0.0 --port ${PORT}"]
