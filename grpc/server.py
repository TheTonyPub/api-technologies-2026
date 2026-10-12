from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

import chebupizza_pb2
import chebupizza_pb2_grpc

CALORIES_PER_PIECE = 270
PRICE_PER_PIECE = 65.0


def check_meal(meal, context):
    if meal.pieces < 1:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "pieces must be >= 1")


def get_verdict(pieces):
    if pieces <= 2:
        return "нормально"
    if pieces <= 5:
        return "ну такое"
    return "может хватит"


class ChebupizzaService(chebupizza_pb2_grpc.ChebupizzaServiceServicer):
    # unary
    def RateMeal(self, request, context):
        check_meal(request, context)
        return chebupizza_pb2.MealInfo(
            calories=request.pieces * CALORIES_PER_PIECE,
            cost_rub=request.pieces * PRICE_PER_PIECE,
            verdict=get_verdict(request.pieces),
        )

    # server streaming
    def EatingPlan(self, request, context):
        if request.total_pieces < 1 or request.per_day < 1:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "total_pieces and per_day must be >= 1")
        if request.total_pieces > 1000:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "total_pieces must be <= 1000")

        left = request.total_pieces
        day = 0
        while left > 0:
            day += 1
            today = min(request.per_day, left)
            left -= today
            yield chebupizza_pb2.DayPlan(day=day, pieces=today, left=left)

    # client streaming
    def SummarizeMeals(self, request_iterator, context):
        count = 0
        total = 0
        for meal in request_iterator:
            check_meal(meal, context)
            count += 1
            total += meal.pieces

        average = total / count if count > 0 else 0
        return chebupizza_pb2.Summary(
            meal_count=count,
            total_pieces=total,
            total_calories=total * CALORIES_PER_PIECE,
            average_pieces=average,
        )

    # bidirectional streaming: ответ уходит сразу после каждого приёма, не ждём конца
    def LiveCounter(self, request_iterator, context):
        count = 0
        total = 0
        for meal in request_iterator:
            check_meal(meal, context)
            count += 1
            total += meal.pieces
            yield chebupizza_pb2.RunningTotal(
                meals=count,
                total_pieces=total,
                total_calories=total * CALORIES_PER_PIECE,
                message="уже " + str(total) + " шт.",
            )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chebupizza_pb2_grpc.add_ChebupizzaServiceServicer_to_server(ChebupizzaService(), server)

    # reflection нужен, чтобы grpcurl видел методы без proto-файла
    names = (
        chebupizza_pb2.DESCRIPTOR.services_by_name["ChebupizzaService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(names, server)

    server.add_insecure_port("[::]:50051")
    server.start()
    print("gRPC server started on port 50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
