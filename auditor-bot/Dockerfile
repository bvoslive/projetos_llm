FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências primeiro (melhor cache de camadas)
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[api,dashboard,anthropic,openai]"

COPY data ./data
COPY dashboard ./dashboard

# Não roda como root
RUN useradd --create-home app && mkdir -p /app/reports /app/state && chown -R app /app
USER app

ENV FISCAL_KB_PATH=/app/data/loja_pitanga/kb.yaml \
    FISCAL_DB_PATH=/app/state/fiscal.db

EXPOSE 8000 8501
CMD ["uvicorn", "fiscal.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
