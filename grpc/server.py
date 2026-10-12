"""gRPC-сервис оценки риска оттока клиента (ДЗ семинара 6).

Сервер слушает порт 50051. Код churn_pb2.py / churn_pb2_grpc.py сгенерирован
из proto/churn.proto:

    python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/churn.proto
"""

from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

import churn_pb2
import churn_pb2_grpc

PORT = 50051


def calculate(customer_id: str, tenure: int, spend: float, tickets: int) -> churn_pb2.Prediction:
    # Та же формула, что и в REST-сервисе; скор ограничен диапазоном [0, 1].
    score = min(1.0, max(0.0, 0.65 - 0.004 * tenure + 0.0008 * spend + 0.04 * tickets))

    return churn_pb2.Prediction(
        customer_id=customer_id,
        tenure_months=tenure,
        risk_score=round(score, 3),
        risk_label="high" if score >= 0.6 else "low",
    )


def check(context, req) -> None:
    if req.tenure_months < 0 or req.monthly_spend < 0 or req.support_tickets < 0:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "значения не могут быть отрицательными")


class ChurnService(churn_pb2_grpc.ChurnServiceServicer):
    def Predict(self, request, context):
        # unary: один клиент -> один расчёт.
        check(context, request)

        return calculate(
            request.customer_id, request.tenure_months,
            request.monthly_spend, request.support_tickets
        )

    def PredictHistory(self, request, context):
        # server streaming: риск по месяцам стажа от 1 до months (минимум 1, максимум 120).
        months = min(max(request.months, 1), 120)

        for m in range(1, months + 1):
            yield calculate(
                request.customer_id, m,
                request.monthly_spend, request.support_tickets
            )

    def PredictBatch(self, request_iterator, context):
        # client streaming: читаем всех клиентов, в конце отдаём одну сводку.
        total = high = 0
        risk_sum = 0.0

        for req in request_iterator:
            check(context, req)
            p = calculate(
                req.customer_id, req.tenure_months,
                req.monthly_spend, req.support_tickets
            )
            total += 1
            high += p.risk_label == "high"
            risk_sum += p.risk_score

        return churn_pb2.BatchSummary(
            total=total,
            high_risk_count=high,
            average_risk=round(risk_sum / total, 3) if total else 0.0,
        )

    def PredictLive(self, request_iterator, context):
        # bidirectional: на каждый входящий запрос сразу отвечаем.
        for req in request_iterator:
            check(context, req)

            yield calculate(
                req.customer_id, req.tenure_months,
                req.monthly_spend, req.support_tickets
            )


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    churn_pb2_grpc.add_ChurnServiceServicer_to_server(ChurnService(), server)
    service_names = (
        churn_pb2.DESCRIPTOR.services_by_name["ChurnService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    print(f"gRPC server listening on :{PORT}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
