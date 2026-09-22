FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && addgroup -S app \
    && adduser -S -G app app \
    && mkdir -p /data \
    && chown -R app:app /app /data

COPY --chown=app:app services ./services

USER app

EXPOSE 8000

CMD ["uvicorn", "services.ml_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
