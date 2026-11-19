import os
import math
import dill
from minio import Minio
from urllib3 import PoolManager, Timeout


EXPECTED_FEATURES = [
    "amount",
    "avg_amount_30d",
    "tx_count_24h",
    "geo_risk",
    "merchant_risk",
    "hour",
]


def load_model():
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ROOT_USER")
    secret_key = os.getenv("MINIO_ROOT_PASSWORD")
    bucket = os.getenv("MODEL_BUCKET", "antifraud-models")
    object_name = os.getenv("MODEL_OBJECT", "antifraud-v1.dill")
    local_path = os.getenv("MODEL_PATH", "/tmp/antifraud-v1.dill")

    if not access_key or not secret_key:
        raise RuntimeError("MinIO credentials are not configured")

    http_client = PoolManager(
        timeout=Timeout(connect=5.0, read=30.0),
        retries=False
    )

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
        http_client=http_client
    )

    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)

    try:
        client.fget_object(bucket, object_name, local_path)
    except Exception as error:
        raise RuntimeError(
            f"Failed to download model '{object_name}' from bucket '{bucket}'"
        ) from error

    try:
        with open(local_path, "rb") as file:
            artifact = dill.load(file)
    except Exception as error:
        raise RuntimeError("Failed to read model artifact") from error

    if not isinstance(artifact, dict):
        raise RuntimeError("Model artifact must be a dictionary")

    if "model" not in artifact or "meta" not in artifact:
        raise RuntimeError("Model artifact must contain 'model' and 'meta'")

    metadata = artifact["meta"]

    if not isinstance(metadata, dict):
        raise RuntimeError("Model metadata must be a dictionary")

    required_metadata = {"name", "version", "threshold", "features"}
    missing_metadata = required_metadata - metadata.keys()

    if missing_metadata:
        raise RuntimeError(
            f"Model metadata is missing fields: {', '.join(sorted(missing_metadata))}"
        )

    if metadata["features"] != EXPECTED_FEATURES:
        raise RuntimeError(
            f"Model features do not match expected order: {EXPECTED_FEATURES}"
        )

    threshold = metadata["threshold"]

    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise RuntimeError("Model threshold must be a number between 0 and 1")

    return artifact["model"], metadata
