import asyncio
import json
import os

import nats
from nats.js.api import ConsumerConfig, DeliverPolicy, StreamConfig, StorageType
from nats.js.errors import NotFoundError


async def ensure_stream(js) -> None:
    try:
        await js.stream_info("INFERENCE")
    except NotFoundError:
        try:
            await js.add_stream(
                StreamConfig(
                    name="INFERENCE",
                    subjects=["inference.request.*", "inference.result.*"],
                    storage=StorageType.FILE,
                    max_age=7 * 24 * 60 * 60,
                )
            )
        except Exception:
            # The API may have created the stream concurrently.
            await js.stream_info("INFERENCE")


async def predict(js, job_id: str, records: list[dict]) -> dict:
    # A result lookup makes redelivery after publish-before-ack idempotent.
    try:
        previous = await js.get_last_msg("INFERENCE", f"inference.result.{job_id}")
        return json.loads(previous.data)
    except NotFoundError:
        pass

    await asyncio.sleep(1)
    results = []
    for record in records:
        normalized_usage = round(float(record["monthly_usage"]) / 1000.0, 3)
        score = min(
            1.0,
            max(0.0, 0.15 + normalized_usage + 0.08 * int(record["support_tickets"])),
        )
        results.append(
            {
                "customer_id": record["customer_id"],
                "normalized_usage": normalized_usage,
                "risk_score": round(score, 3),
                "risk_label": "high" if score >= 0.6 else "low",
            }
        )
    result = {"job_id": job_id, "status": "completed", "results": results}
    await js.publish(
        f"inference.result.{job_id}",
        json.dumps(result).encode(),
        headers={"Nats-Msg-Id": f"result-{job_id}"},
    )
    return result


async def run() -> None:
    nc = await nats.connect(os.getenv("NATS_URL", "nats://nats:4222"))
    js = nc.jetstream()
    await ensure_stream(js)
    subscription = await js.pull_subscribe(
        "inference.request.*",
        durable="inference-worker",
        config=ConsumerConfig(
            durable_name="inference-worker",
            deliver_policy=DeliverPolicy.ALL,
            ack_wait=30,
            max_deliver=10,
        ),
    )
    while True:
        try:
            messages = await subscription.fetch(1, timeout=5)
        except nats.errors.TimeoutError:
            continue
        for message in messages:
            try:
                request = json.loads(message.data)
                job_id = request["job_id"]
                try:
                    result = await predict(js, job_id, request["records"])
                except Exception as exc:
                    result = {
                        "job_id": job_id,
                        "status": "failed",
                        "error": f"inference_failed: {type(exc).__name__}",
                    }
                    await js.publish(
                        f"inference.result.{job_id}",
                        json.dumps(result).encode(),
                        headers={"Nats-Msg-Id": f"result-{job_id}"},
                    )
                await message.ack()
            except Exception:
                await message.nak(delay=2)


if __name__ == "__main__":
    asyncio.run(run())
