from concurrent import futures

import grpc
import pandas as pd

from services.ml_service.model_loader import load_model
from services.ml_service.proto import ml_service_pb2
from services.ml_service.proto import ml_service_pb2_grpc


FEATURES = [
    "amount",
    "avg_amount_30d",
    "tx_count_24h",
    "geo_risk",
    "merchant_risk",
    "hour",
]


class MLServiceServicer(ml_service_pb2_grpc.MLServiceServicer):
    def __init__(self):
        self.model, self.model_meta = load_model()

    def CheckTransaction(self, request, context):
        features = request.features

        data = pd.DataFrame(
            [[
                features.amount,
                features.avg_amount_30d,
                features.tx_count_24h,
                features.geo_risk,
                features.merchant_risk,
                features.hour,
            ]],
            columns=FEATURES,
        )

        score = float(self.model.predict_proba(data)[0][1])

        return ml_service_pb2.InferenceResponse(
            transaction_id=request.transaction_id,
            score=round(score, 6),
            actual_result=(
                "fraud"
                if score >= self.model_meta["threshold"]
                else "normal"
            ),
            tool="ML Service",
            version=self.model_meta["version"],
            action="scoring",
        )


def serve():
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10)
    )

    ml_service_pb2_grpc.add_MLServiceServicer_to_server(
        MLServiceServicer(),
        server,
    )

    server.add_insecure_port("[::]:50051")
    server.start()

    print("ML Service gRPC server started on port 50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
