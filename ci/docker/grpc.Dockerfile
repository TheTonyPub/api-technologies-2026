# Образ, в котором CI запускает grpc/. Студентам менять не нужно.
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --only-binary=:all: -r requirements.txt \
    && adduser -D -H -u 10001 app \
    && chown app /app

COPY --chown=app:app . .

USER app

EXPOSE 50051

CMD ["python", "server.py"]
