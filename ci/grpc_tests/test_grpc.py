"""Проверки gRPC-сервиса из папки grpc.

Сервис уже запущен (ci/run_grpc.sh поднимает контейнер с python server.py).
Тесты компилируют .proto студента, находят в нём сервисы и вызывают каждый
метод с автоматически заполненными сообщениями. Если автоматических значений
недостаточно, положите свои запросы в grpc/ci_examples.json:

    {"GetItem": [{"id": "1"}], "CreateItems": [{"id": "1"}, {"id": "2"}]}
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import grpc
import grpc_tools
import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.descriptor import FieldDescriptor
from grpc_tools import protoc

GRPC_DIR = Path(os.environ.get("GRPC_DIR", "grpc")).resolve()
TARGET = os.environ.get("GRPC_TARGET", "localhost:50051")
TIMEOUT = 15
STREAM_SIZE = 3
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules"}

KINDS = {
    (False, False): "unary",
    (False, True): "server streaming",
    (True, False): "client streaming",
    (True, True): "bidirectional streaming",
}


def student_files(pattern: str) -> list[Path]:
    return sorted(
        p for p in GRPC_DIR.rglob(pattern) if not SKIP_DIRS.intersection(p.relative_to(GRPC_DIR).parts)
    )


# --- Фикстуры --------------------------------------------------------------


@pytest.fixture(scope="session")
def proto_files() -> list[Path]:
    files = student_files("*.proto")
    assert files, "В папке grpc/ нет ни одного .proto файла"
    return files


@pytest.fixture(scope="session")
def pool(proto_files: list[Path], tmp_path_factory) -> descriptor_pool.DescriptorPool:
    out = tmp_path_factory.mktemp("descriptors")
    well_known = Path(grpc_tools.__file__).parent / "_proto"
    pool = descriptor_pool.DescriptorPool()
    added: set[str] = set()
    for index, proto in enumerate(proto_files):
        target = out / f"set{index}.pb"
        args = [
            "protoc",
            f"-I{proto.parent}",
            f"-I{GRPC_DIR}",
            f"-I{well_known}",
            "--include_imports",
            f"--descriptor_set_out={target}",
            str(proto),
        ]
        code = protoc.main(args)
        assert code == 0, f"{proto.relative_to(GRPC_DIR)}: .proto не компилируется (см. вывод protoc выше)"
        fds = descriptor_pb2.FileDescriptorSet.FromString(target.read_bytes())
        for file_proto in fds.file:
            if file_proto.name not in added:
                pool.Add(file_proto)
                added.add(file_proto.name)
    return pool


@pytest.fixture(scope="session")
def methods(pool, proto_files):
    found = []
    for proto in proto_files:
        rel = str(proto.relative_to(proto.parent))
        try:
            file_desc = pool.FindFileByName(rel)
        except KeyError:
            continue
        for service in file_desc.services_by_name.values():
            for method in service.methods:
                found.append(method)
    assert found, "В .proto файлах не описано ни одного service с rpc-методами"
    return found


@pytest.fixture(scope="session")
def channel():
    ch = grpc.insecure_channel(TARGET)
    try:
        grpc.channel_ready_future(ch).result(timeout=30)
    except grpc.FutureTimeoutError:
        pytest.fail(f"Не удалось подключиться к gRPC-серверу {TARGET}")
    yield ch
    ch.close()


@pytest.fixture(scope="session")
def examples() -> dict:
    path = GRPC_DIR / "ci_examples.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


# --- Генерация сообщений ---------------------------------------------------


def fill(desc, index: int = 0, depth: int = 0):
    message = message_factory.GetMessageClass(desc)()
    if depth > 4:
        return message
    if desc.full_name == "google.protobuf.Timestamp":
        message.GetCurrentTime()
        return message
    filled_oneofs: set[str] = set()
    for field in desc.fields:
        oneof = field.containing_oneof
        if oneof is not None:
            if oneof.name in filled_oneofs:
                continue
            filled_oneofs.add(oneof.name)
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            key_field = field.message_type.fields_by_name["key"]
            value_field = field.message_type.fields_by_name["value"]
            key = scalar(key_field, index)
            container = getattr(message, field.name)
            if value_field.message_type is not None:
                container[key].CopyFrom(fill(value_field.message_type, index, depth + 1))
            else:
                container[key] = scalar(value_field, index)
            continue
        repeated = field.label == FieldDescriptor.LABEL_REPEATED
        count = 2 if repeated else 1
        for i in range(count):
            item_index = index * count + i
            if field.message_type is not None:
                value = fill(field.message_type, item_index, depth + 1)
                if repeated:
                    getattr(message, field.name).add().CopyFrom(value)
                else:
                    getattr(message, field.name).CopyFrom(value)
            else:
                value = scalar(field, item_index)
                if repeated:
                    getattr(message, field.name).append(value)
                else:
                    setattr(message, field.name, value)
    return message


def scalar(field, index: int):
    t = field.type
    if t == FieldDescriptor.TYPE_STRING:
        name = field.name.lower()
        if "email" in name:
            return f"student{index + 1}@example.com"
        return f"{field.name}-{index + 1}"
    if t == FieldDescriptor.TYPE_BYTES:
        return b"data"
    if t == FieldDescriptor.TYPE_BOOL:
        return True
    if t in (FieldDescriptor.TYPE_DOUBLE, FieldDescriptor.TYPE_FLOAT):
        return 1.0
    if t == FieldDescriptor.TYPE_ENUM:
        values = [v.number for v in field.enum_type.values if v.number != 0]
        return values[0] if values else 0
    return 1


def requests_for(method, examples: dict, count: int):
    custom = examples.get(method.name) or examples.get(f"{method.containing_service.full_name}/{method.name}")
    cls = message_factory.GetMessageClass(method.input_type)
    if custom:
        return [json_format.ParseDict(item, cls()) for item in custom][:count]
    return [fill(method.input_type, i) for i in range(count)]


# --- Тесты -----------------------------------------------------------------


def test_requirements_txt():
    path = GRPC_DIR / "requirements.txt"
    assert path.is_file(), "В корне grpc/ должен лежать requirements.txt"
    names = {
        re.split(r"[\s\[<>=!~;]", line.strip(), maxsplit=1)[0].lower()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for package in ("grpcio", "protobuf"):
        assert package in names, f"В grpc/requirements.txt нет зависимости {package}"


def test_generated_code_present(pool, proto_files):
    generated = {p.name for p in student_files("*.py")}
    for proto in proto_files:
        stem = proto.stem
        assert f"{stem}_pb2.py" in generated, f"Нет сгенерированного файла {stem}_pb2.py для {proto.name}"
        file_desc = pool.FindFileByName(str(proto.relative_to(proto.parent)))
        if file_desc.services_by_name:
            assert f"{stem}_pb2_grpc.py" in generated, (
                f"Нет сгенерированного файла {stem}_pb2_grpc.py для {proto.name}"
            )


def test_all_four_interaction_types(methods):
    present = {KINDS[(m.client_streaming, m.server_streaming)] for m in methods}
    missing = [kind for kind in KINDS.values() if kind not in present]
    assert not missing, f"В .proto нет типов взаимодействия: {', '.join(missing)}"


def test_every_method_works(methods, channel, examples):
    failures = []
    for method in methods:
        kind = KINDS[(method.client_streaming, method.server_streaming)]
        path = f"/{method.containing_service.full_name}/{method.name}"
        req_cls = message_factory.GetMessageClass(method.input_type)
        resp_cls = message_factory.GetMessageClass(method.output_type)
        stub_args = dict(request_serializer=req_cls.SerializeToString, response_deserializer=resp_cls.FromString)
        requests = requests_for(method, examples, STREAM_SIZE if method.client_streaming else 1)
        try:
            if kind == "unary":
                responses = [channel.unary_unary(path, **stub_args)(requests[0], timeout=TIMEOUT)]
            elif kind == "server streaming":
                responses = list(channel.unary_stream(path, **stub_args)(requests[0], timeout=TIMEOUT))
            elif kind == "client streaming":
                responses = [channel.stream_unary(path, **stub_args)(iter(requests), timeout=TIMEOUT)]
            else:
                responses = list(channel.stream_stream(path, **stub_args)(iter(requests), timeout=TIMEOUT))
        except grpc.RpcError as error:
            sent = [json_format.MessageToDict(r) for r in requests]
            failures.append(
                f"{path} ({kind}): {error.code().name} {error.details()!r}\n    запрос: {json.dumps(sent, ensure_ascii=False)}"
            )
            continue
        if not responses:
            failures.append(f"{path} ({kind}): сервер не вернул ни одного сообщения")
        else:
            print(f"{path} ({kind}) -> {len(responses)} ответ(ов): "
                  f"{json.dumps(json_format.MessageToDict(responses[0]), ensure_ascii=False)}")
    assert not failures, (
        "Методы завершились ошибкой:\n  " + "\n  ".join(failures)
        + "\nЕсли методу нужны особые значения, добавьте их в grpc/ci_examples.json"
    )
