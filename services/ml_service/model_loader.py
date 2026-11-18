import os
import dill
from minio import Minio


def load_model():
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ROOT_USER")
    secret_key = os.getenv("MINIO_ROOT_PASSWORD")
    bucket = os.getenv("MODEL_BUCKET", "antifraud-models")
    object_name = os.getenv("MODEL_OBJECT", "antifraud-v1.dill")
    local_path = os.getenv("MODEL_PATH", "/tmp/antifraud-v1.dill")

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False
    )

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    client.fget_object(
        bucket,
        object_name,
        local_path
    )

    with open(local_path, "rb") as file:
        artifact = dill.load(file)

    return artifact["model"], artifact["meta"]
