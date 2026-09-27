FROM dockerhub.timeweb.cloud/python:3.13-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/grpc/requirements.txt .
RUN pip install --only-binary=:all: --no-cache-dir -r requirements.txt \
    && adduser -D -H -u 10001 appuser
COPY services/grpc/server.py ./server.py
COPY services/grpc/transaction_pb2.py services/grpc/transaction_pb2_grpc.py ./
USER 10001:10001
EXPOSE 8012
CMD ["python", "server.py"]
