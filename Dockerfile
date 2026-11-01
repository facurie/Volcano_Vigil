# The Volcano Vigil image, built by the Hugging Face Docker Space (docs/DEPLOY.md).

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 vigil
WORKDIR /app

COPY deploy/constraints.txt deploy/constraints.txt
COPY pyproject.toml README.md LICENSE ./
COPY vigil vigil
RUN pip install --no-cache-dir -c deploy/constraints.txt .
COPY config config
COPY deploy/start.sh deploy/start.sh
RUN mkdir data && chown vigil:vigil data

USER vigil
ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    DB_PATH=/app/data/vigil.sqlite \
    DAILY_BUDGET_USD=5 \
    ALERT_RESERVE_USD=0.75 \
    HF_HUB_DISABLE_PROGRESS_BARS=1
EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
