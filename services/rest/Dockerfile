FROM dockerhub.timeweb.cloud/python:3.13-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/rest/requirements.txt ./requirements.txt
RUN pip install --only-binary=:all: --no-cache-dir -r requirements.txt \
    && adduser -D -H -u 10001 appuser
COPY services/rest/main.py ./main.py
USER 10001:10001
EXPOSE 8011
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8011"]
