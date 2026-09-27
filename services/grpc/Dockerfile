FROM python:3.13-alpine AS codegen
ENV PIP_NO_CACHE_DIR=1
RUN pip install --only-binary=:all: --no-cache-dir grpcio-tools==1.71.0
WORKDIR /build
COPY proto/transaction.proto ./transaction.proto
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. transaction.proto

FROM python:3.13-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/grpc/requirements.txt .
RUN pip install --only-binary=:all: --no-cache-dir -r requirements.txt \
    && adduser -D -H -u 10001 appuser
COPY services/grpc/server.py ./server.py
COPY --from=codegen /build/transaction_pb2.py /build/transaction_pb2_grpc.py ./
USER 10001:10001
EXPOSE 8012
CMD ["python", "server.py"]
