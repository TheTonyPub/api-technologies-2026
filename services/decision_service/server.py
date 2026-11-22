import grpc
from concurrent import futures
import os
import redis

# Импорт сгенерированных proto-файлов
from services.decision_service.proto import decision_pb2
from services.decision_service.proto import decision_pb2_grpc

# Настройка подключения к Redis
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

class DecisionService(decision_pb2_grpc.DecisionServiceServicer):
    def MakeDecision(self, request, context):
        print(f"Получен запрос: tx={request.transaction_id}, score={request.score}, threshold={request.threshold}")
        
        # Логика вынесения вердикта
        if request.score >= request.threshold:
            verdict = 1
        else:
            verdict = 0
            
        # Сохраняем вердикт в Redis
        try:
            redis_client.set(f"verdict:{request.transaction_id}", verdict)
            print(f"Вердикт {verdict} сохранен для {request.transaction_id}")
        except Exception as e:
            print(f"Ошибка Redis: {e}")
        
        return decision_pb2.DecisionResponse(
            transaction_id=request.transaction_id,
            verdict=verdict,
            status="success"
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    decision_pb2_grpc.add_DecisionServiceServicer_to_server(DecisionService(), server)
    
    port = os.getenv("DECISION_GRPC_PORT", "50052")
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f"Decision gRPC Service запущен на порту {port}")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
