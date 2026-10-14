"""Проверки REST-сервиса из папки rest-api.

Сервис уже запущен (ci/run_rest.sh поднимает контейнер через uvicorn).
Все запросы строятся по схеме /openapi.json, поэтому тесты подходят и для
user-service из семинара 3, и для собственной предметной области.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator

from openapi_tools import (
    HTTP_METHODS,
    Operation,
    Resource,
    SchemaError,
    Spec,
    extract_id,
    find_resources,
    missing_id,
)

BASE_URL = os.environ.get("REST_BASE_URL", "http://localhost:8000")
REST_DIR = Path(os.environ.get("REST_DIR", "rest-api"))
VALIDATION_CODES = (400, 422)

CALLED: set[str] = set()


# --- HTTP-клиент с журналом ------------------------------------------------


class Client:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=BASE_URL, timeout=15)
        self.log: list[str] = []

    def call(self, op: Operation, params: dict | None = None, body: Any = None, query: dict | None = None):
        path = op.path
        for key, value in (params or {}).items():
            path = path.replace("{" + key + "}", str(value))
        kwargs: dict[str, Any] = {"params": query or {}}
        if body is not None:
            kwargs["json"] = body
        response = self.http.request(op.method.upper(), path, **kwargs)
        CALLED.add(op.name)
        text = response.text if len(response.text) < 600 else response.text[:600] + "..."
        sent = f" body={json.dumps(body, ensure_ascii=False)}" if body is not None else ""
        self.log.append(f"{op.method.upper()} {path}{sent} -> {response.status_code} {text}")
        return response

    @property
    def last(self) -> str:
        return "\n  Запрос: " + (self.log[-1] if self.log else "—")


@pytest.fixture(scope="session")
def client() -> Client:
    return Client()


@pytest.fixture(scope="session")
def spec() -> Spec:
    response = httpx.get(f"{BASE_URL}/openapi.json", timeout=15)
    assert response.status_code == 200, f"/openapi.json вернул {response.status_code}"
    return Spec(response.json())


@pytest.fixture(scope="session")
def resources(spec: Spec) -> list[Resource]:
    found = find_resources(spec)
    assert found, (
        "Не найден ресурс с полным набором CRUD. Ожидается POST /<resource> и "
        "GET, PUT, DELETE /<resource>/{id} (например, POST /v1/user и "
        "GET/PUT/DELETE /v1/user/{user_id})."
    )
    return found


def query_for(spec: Spec, op: Operation, variant: int = 0) -> dict:
    query = {}
    for param in op.spec.get("parameters", []):
        param = spec.resolve(param)
        if param.get("in") == "query" and param.get("required"):
            query[param["name"]] = spec.example(param.get("schema", {}), variant, param["name"])
    return query


def check_schema(spec: Spec, op: Operation, response: httpx.Response, log: str) -> None:
    _, schema = spec.success_response(op)
    if not schema or response.status_code == 204 or not response.content:
        return
    validator = Draft202012Validator({**schema, "components": spec.doc.get("components", {})})
    errors = sorted(validator.iter_errors(response.json()), key=lambda e: list(e.path))
    assert not errors, (
        f"{op.name}: ответ не соответствует схеме из OpenAPI: {errors[0].message}{log}"
    )


def same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return math.isclose(float(expected), float(actual), rel_tol=1e-6)
        except (TypeError, ValueError):
            return False
    return expected == actual


def assert_fields(sent: Any, received: Any, op: Operation, log: str) -> None:
    if not isinstance(sent, dict) or not isinstance(received, dict):
        return
    for key, value in sent.items():
        if key in received and isinstance(value, (str, int, float, bool)):
            assert same(value, received[key]), (
                f"{op.name}: поле '{key}' равно {received[key]!r}, ожидалось {value!r}{log}"
            )


def create(spec: Spec, client: Client, resource: Resource, variant: int = 0) -> tuple[Any, Any]:
    body = spec.body(resource.create, variant)
    response = client.call(resource.create, body=body, query=query_for(spec, resource.create, variant))
    assert response.status_code in (200, 201), (
        f"{resource.create.name}: ожидался 201 (или 200), получен {response.status_code}{client.last}"
    )
    check_schema(spec, resource.create, response, client.last)
    payload = response.json() if response.content else None
    object_id = extract_id(payload, response.headers, resource.id_param)
    assert object_id is not None, (
        f"{resource.create.name}: в ответе нет идентификатора созданного объекта "
        f"(ожидалось поле '{resource.id_param}' или 'id'){client.last}"
    )
    return object_id, body


# --- Файлы и запуск --------------------------------------------------------


def test_main_py_exists():
    assert (REST_DIR / "main.py").is_file(), "В корне rest-api/ должен лежать main.py"


def test_requirements_contain_fastapi_and_uvicorn():
    path = REST_DIR / "requirements.txt"
    assert path.is_file(), "В корне rest-api/ должен лежать requirements.txt"
    names = {
        re.split(r"[\s\[<>=!~;]", line.strip(), maxsplit=1)[0].lower()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for package in ("fastapi", "uvicorn"):
        assert package in names, f"В rest-api/requirements.txt нет зависимости {package}"


def test_openapi_is_available(spec: Spec):
    assert spec.doc.get("paths"), "В /openapi.json нет ни одного пути"


# --- Контракт --------------------------------------------------------------


def test_all_four_http_methods_present(spec: Spec):
    methods = {op.method for op in spec.operations()}
    missing = [m.upper() for m in HTTP_METHODS if m not in methods]
    assert not missing, f"В OpenAPI нет методов: {', '.join(missing)}"


def test_request_bodies_are_models(spec: Spec):
    for op in spec.operations():
        if op.method not in ("post", "put"):
            continue
        schema = spec.request_schema(op)
        assert schema is not None, f"{op.name}: тело запроса должно быть JSON-моделью (pydantic BaseModel)"
        flat = spec.flatten(schema)
        assert flat.get("properties"), f"{op.name}: модель запроса должна описывать поля"


def test_request_models_use_field_validation(spec: Spec):
    for op in spec.operations():
        if op.method not in ("post", "put"):
            continue
        schema = spec.request_schema(op)
        assert schema is not None and spec.has_constraints(schema), (
            f"{op.name}: в модели запроса нет ограничений. Опишите поля через "
            "Field(ge=..., le=..., min_length=..., max_length=..., pattern=...)"
        )


def test_responses_are_models(spec: Spec):
    for op in spec.operations():
        if op.method not in ("get", "post", "put"):
            continue
        code, schema = spec.success_response(op)
        assert code is not None, f"{op.name}: в OpenAPI не описан успешный ответ 2xx"
        assert schema, (
            f"{op.name}: у ответа {code} нет схемы. Укажите response_model "
            "или аннотацию возвращаемого типа"
        )


# --- Поведение -------------------------------------------------------------


def test_crud_flow(spec: Spec, client: Client, resources: list[Resource]):
    for resource in resources:
        object_id, created = create(spec, client, resource)
        params = {resource.id_param: object_id}

        response = client.call(resource.read, params, query=query_for(spec, resource.read))
        assert response.status_code == 200, (
            f"{resource.read.name}: созданный объект не читается ({response.status_code}){client.last}"
        )
        check_schema(spec, resource.read, response, client.last)
        assert_fields(created, response.json(), resource.read, client.last)

        update = spec.body(resource.update, variant=1)
        response = client.call(resource.update, params, body=update, query=query_for(spec, resource.update))
        assert 200 <= response.status_code < 300, (
            f"{resource.update.name}: ожидался 2xx, получен {response.status_code}{client.last}"
        )
        check_schema(spec, resource.update, response, client.last)

        response = client.call(resource.read, params, query=query_for(spec, resource.read))
        assert response.status_code == 200, f"{resource.read.name}: {response.status_code}{client.last}"
        assert_fields(update, response.json(), resource.read, client.last + "\n  (изменения после PUT не сохранились)")

        response = client.call(resource.delete, params, query=query_for(spec, resource.delete))
        assert response.status_code in (200, 202, 204), (
            f"{resource.delete.name}: ожидался 204 (или 200), получен {response.status_code}{client.last}"
        )

        response = client.call(resource.read, params, query=query_for(spec, resource.read))
        assert response.status_code == 404, (
            f"{resource.read.name}: после DELETE ожидался 404, получен {response.status_code}{client.last}"
        )


def test_missing_object_returns_404(spec: Spec, client: Client, resources: list[Resource]):
    for resource in resources:
        params = {resource.id_param: missing_id(spec.param_schema(resource.read, resource.id_param))}
        for op, body in (
            (resource.read, None),
            (resource.update, spec.body(resource.update, variant=1)),
            (resource.delete, None),
        ):
            response = client.call(op, params, body=body, query=query_for(spec, op))
            assert response.status_code == 404, (
                f"{op.name}: для несуществующего объекта ожидался 404, получен "
                f"{response.status_code}{client.last}"
            )


@pytest.mark.parametrize("kind", ["create", "update"])
def test_invalid_payload_is_rejected(spec: Spec, client: Client, resources: list[Resource], kind: str):
    for resource in resources:
        params = {}
        if kind == "update":
            object_id, _ = create(spec, client, resource)
            params = {resource.id_param: object_id}
        op = getattr(resource, kind)
        cases = list(spec.invalid_bodies(op))
        if kind == "update" and not cases:
            continue
        assert cases, f"{op.name}: не из чего построить некорректный запрос — добавьте ограничения в Field"
        for description, body in cases:
            response = client.call(op, params, body=body, query=query_for(spec, op))
            assert response.status_code in VALIDATION_CODES, (
                f"{op.name}: запрос с ошибкой ({description}) должен вернуть 422, "
                f"получен {response.status_code}{client.last}"
            )


def test_every_operation_responds_without_server_error(spec: Spec, client: Client, resources: list[Resource]):
    """Дёргает каждую операцию GET/POST/PUT/DELETE из схемы хотя бы раз."""
    by_param = {r.id_param: r for r in resources}
    ordered = sorted(spec.operations(), key=lambda op: op.method == "delete")
    for op in ordered:
        params = {}
        for name in op.path_params:
            resource = by_param.get(name)
            if resource is not None:
                params[name], _ = create(spec, client, resource, variant=2)
            else:
                try:
                    params[name] = spec.example(spec.param_schema(op, name), 0, name)
                except SchemaError as exc:
                    pytest.fail(f"{op.name}: {exc}")
        try:
            body = spec.body(op, variant=2) if op.method in ("post", "put") else None
        except SchemaError as exc:
            pytest.fail(f"{op.name}: {exc}")
        response = client.call(op, params, body=body, query=query_for(spec, op, 2))
        assert response.status_code < 500, (
            f"{op.name}: сервер вернул {response.status_code}{client.last}"
        )
    not_called = sorted(op.name for op in spec.operations() if op.name not in CALLED)
    assert not not_called, f"Не вызваны операции: {', '.join(not_called)}"
