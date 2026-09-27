FROM dockerhub.timeweb.cloud/python:3.13-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/event_worker/requirements.txt ./requirements.txt
RUN pip install --only-binary=:all: --no-cache-dir -r requirements.txt \
    && adduser -D -H -u 10001 appuser
COPY services/event_worker/worker.py ./worker.py
USER 10001:10001
CMD ["python", "worker.py"]
