from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

import transaction_pb2
import transaction_pb2_grpc


SERVICE = "seminar04.v1.TransactionInference"


class TransactionInference(transaction_pb2_grpc.TransactionInferenceServicer):
    def PredictBatch(self, request, context):
        if not request.transactions:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "transactions must contain at least one item")
        if len(request.transactions) > 100:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "transactions must contain at most 100 items")

        predictions = []
        for transaction in request.transactions:
            if not transaction.id.strip():
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "transaction id must not be empty")
            if transaction.amount < 0:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "amount must be non-negative")
            if not 0 <= transaction.merchant_risk <= 1:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "merchant_risk must be between 0 and 1")
            score = min(
                1.0,
                max(
                    0.0,
                    0.1
                    + min(transaction.amount, 5000.0) / 10000.0
                    + (0.25 if transaction.international else 0.0)
                    + 0.5 * transaction.merchant_risk,
                ),
            )
            predictions.append(
                transaction_pb2.TransactionPrediction(
                    id=transaction.id,
                    risk_score=round(score, 3),
                    risk_label="high" if score >= 0.6 else "low",
                )
            )
        return transaction_pb2.PredictBatchResponse(predictions=predictions)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    transaction_pb2_grpc.add_TransactionInferenceServicer_to_server(
        TransactionInference(), server
    )
    reflection.enable_server_reflection((SERVICE, reflection.SERVICE_NAME), server)
    server.add_insecure_port("[::]:8012")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
