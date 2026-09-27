from concurrent import futures
import math

import grpc
from grpc_reflection.v1alpha import reflection

import transaction_pb2
import transaction_pb2_grpc


SERVICE = "seminar04.v1.TransactionInference"
MAX_TRANSACTIONS = 100


def _validate(transaction):
    if not transaction.id.strip():
        return "transaction id must not be empty"
    if not math.isfinite(transaction.amount) or transaction.amount < 0:
        return "amount must be a finite non-negative number"
    if not math.isfinite(transaction.merchant_risk) or not 0 <= transaction.merchant_risk <= 1:
        return "merchant_risk must be between 0 and 1"
    return None


def _predict(transaction):
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
    return transaction_pb2.TransactionPrediction(
        id=transaction.id,
        risk_score=round(score, 3),
        risk_label="high" if score >= 0.6 else "low",
    )


def _check_transaction(transaction, context):
    error = _validate(transaction)
    if error:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, error)


def _iter_transactions(transactions, context):
    count = 0
    for transaction in transactions:
        count += 1
        if count > MAX_TRANSACTIONS:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "transactions must contain at most 100 items",
            )
        _check_transaction(transaction, context)
        yield transaction
    if count == 0:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "transactions must contain at least one item")


class TransactionInference(transaction_pb2_grpc.TransactionInferenceServicer):
    def PredictBatch(self, request, context):
        transactions = list(_iter_transactions(request.transactions, context))
        return transaction_pb2.PredictBatchResponse(
            predictions=[_predict(item) for item in transactions]
        )

    def PredictBatchStream(self, request, context):
        for transaction in _iter_transactions(request.transactions, context):
            yield _predict(transaction)

    def AggregateTransactions(self, request_iterator, context):
        predictions = [_predict(item) for item in _iter_transactions(request_iterator, context)]
        return transaction_pb2.TransactionScoreSummary(
            transaction_count=len(predictions),
            average_risk=round(sum(item.risk_score for item in predictions) / len(predictions), 3),
            high_risk_count=sum(item.risk_label == "high" for item in predictions),
        )

    def PredictLive(self, request_iterator, context):
        for transaction in _iter_transactions(request_iterator, context):
            yield _predict(transaction)


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
