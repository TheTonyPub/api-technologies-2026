"""Шаблон gRPC-сервиса для ДЗ семинара 6.

Основа — gRPC-сервис из семинара 4 (ветка seminar/04-api-interaction-styles).
Сервер слушает порт 50051. Код item_pb2.py / item_pb2_grpc.py сгенерирован
из proto/item.proto (см. README):

    python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/item.proto
"""

from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

import item_pb2
import item_pb2_grpc

PORT = 50051


class ItemService(item_pb2_grpc.ItemServiceServicer):
    def GetItem(self, request, context):
        # TODO: unary — вернуть один Item.
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "GetItem is not implemented")

    def ListItems(self, request, context):
        # TODO: server streaming — yield несколько Item.
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "ListItems is not implemented")

    def CreateItems(self, request_iterator, context):
        # TODO: client streaming — прочитать все Item и вернуть сводку.
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "CreateItems is not implemented")

    def ProcessItems(self, request_iterator, context):
        # TODO: bidirectional streaming — на каждый входящий Item отвечать Item.
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "ProcessItems is not implemented")


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    item_pb2_grpc.add_ItemServiceServicer_to_server(ItemService(), server)
    service_names = (
        item_pb2.DESCRIPTOR.services_by_name["ItemService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    print(f"gRPC server listening on :{PORT}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
