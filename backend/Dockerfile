# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

COPY requirements.txt .
# Cache pip persistant entre deux builds : après une coupure réseau, les paquets
# déjà téléchargés sont réutilisés au lieu d'être retéléchargés.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.txt

COPY app ./app
COPY mcp_server ./mcp_server

RUN useradd --create-home --uid 1000 radar && mkdir -p /data /models /config && chown -R radar /data /models /config
USER radar

EXPOSE 8000 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
