"""Утилиты для тестов, которые строят запросы по схеме OpenAPI сервиса."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

HTTP_METHODS = ("get", "post", "put", "delete")
CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "enum",
    "const",
    "format",
    "minItems",
    "maxItems",
)
PARAM_RE = re.compile(r"\{([^}]+)\}")


class SchemaError(Exception):
    """По схеме не удаётся построить запрос."""


@dataclass
class Operation:
    method: str
    path: str
    spec: dict

    @property
    def name(self) -> str:
        return f"{self.method.upper()} {self.path}"

    @property
    def path_params(self) -> list[str]:
        return PARAM_RE.findall(self.path)


@dataclass
class Resource:
    collection: str
    item: str
    id_param: str
    create: Operation
    read: Operation
    update: Operation
    delete: Operation
    extra: list[Operation] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.item


class Spec:
    def __init__(self, doc: dict):
        self.doc = doc

    # --- навигация по схеме -------------------------------------------------

    def resolve(self, schema: Any) -> Any:
        depth = 0
        while isinstance(schema, dict) and "$ref" in schema:
            depth += 1
            if depth > 50:
                raise SchemaError("Слишком глубокая цепочка $ref")
            ref = schema["$ref"]
            if not ref.startswith("#/"):
                raise SchemaError(f"Внешние $ref не поддерживаются: {ref}")
            node: Any = self.doc
            for part in ref[2:].split("/"):
                node = node[part.replace("~1", "/").replace("~0", "~")]
            extra = {k: v for k, v in schema.items() if k != "$ref"}
            schema = {**node, **extra}
        return schema

    def flatten(self, schema: Any) -> dict:
        """Раскрывает $ref, allOf и выбирает не-null вариант anyOf/oneOf."""
        schema = self.resolve(schema)
        if not isinstance(schema, dict):
            return {}
        if "allOf" in schema:
            merged: dict = {k: v for k, v in schema.items() if k != "allOf"}
            for part in schema["allOf"]:
                part = self.flatten(part)
                props = {**merged.get("properties", {}), **part.get("properties", {})}
                required = list(merged.get("required", [])) + list(part.get("required", []))
                merged = {**part, **merged}
                if props:
                    merged["properties"] = props
                if required:
                    merged["required"] = required
            schema = merged
        for key in ("anyOf", "oneOf"):
            if key in schema:
                options = [self.flatten(o) for o in schema[key]]
                non_null = [o for o in options if o.get("type") != "null"]
                chosen = non_null[0] if non_null else (options[0] if options else {})
                rest = {k: v for k, v in schema.items() if k != key}
                schema = {**chosen, **rest}
        return schema

    def operations(self) -> list[Operation]:
        result = []
        for path, item in self.doc.get("paths", {}).items():
            for method in HTTP_METHODS:
                if method in item:
                    op = dict(item[method])
                    op["parameters"] = list(item.get("parameters", [])) + list(op.get("parameters", []))
                    result.append(Operation(method, path, op))
        return result

    def request_schema(self, op: Operation) -> Optional[dict]:
        body = op.spec.get("requestBody")
        if not body:
            return None
        body = self.resolve(body)
        content = body.get("content", {})
        media = content.get("application/json")
        if media is None:
            return None
        return media.get("schema")

    def success_response(self, op: Operation) -> tuple[Optional[str], Optional[dict]]:
        responses = op.spec.get("responses", {})
        for code in sorted(responses):
            if str(code).startswith("2"):
                resp = self.resolve(responses[code])
                media = resp.get("content", {}).get("application/json")
                return str(code), (media or {}).get("schema") if media else None
        return None, None

    def param_schema(self, op: Operation, name: str, location: str = "path") -> dict:
        for param in op.spec.get("parameters", []):
            param = self.resolve(param)
            if param.get("name") == name and param.get("in") == location:
                return self.flatten(param.get("schema", {}))
        return {}

    def has_constraints(self, schema: Any, depth: int = 0) -> bool:
        if depth > 6:
            return False
        schema = self.resolve(schema)
        if not isinstance(schema, dict):
            return False
        if any(key in schema for key in CONSTRAINT_KEYS):
            return True
        children = list(schema.get("properties", {}).values())
        for key in ("anyOf", "oneOf", "allOf"):
            children += schema.get(key, [])
        if isinstance(schema.get("items"), dict):
            children.append(schema["items"])
        return any(self.has_constraints(child, depth + 1) for child in children)

    # --- генерация корректных значений --------------------------------------

    def example(self, schema: Any, variant: int = 0, name: str = "", depth: int = 0) -> Any:
        raw = self.resolve(schema)
        if isinstance(raw, dict):
            examples = raw.get("examples")
            if isinstance(examples, list):
                examples = [e for e in examples if e is not None]
                if examples:
                    return examples[variant % len(examples)]
            if raw.get("example") is not None:
                return raw["example"]
        schema = self.flatten(schema)
        if depth > 8:
            raise SchemaError("Слишком глубокая вложенность схемы")
        if "const" in schema:
            return schema["const"]
        examples = schema.get("examples")
        if isinstance(examples, list):
            examples = [e for e in examples if e is not None]
            if examples:
                return examples[variant % len(examples)]
        if schema.get("example") is not None:
            return schema["example"]
        if "enum" in schema:
            values = [v for v in schema["enum"] if v is not None]
            if values:
                return values[variant % len(values)]
        if variant == 0 and schema.get("default") is not None:
            return schema["default"]

        kind = schema.get("type")
        if isinstance(kind, list):
            kind = next((k for k in kind if k != "null"), "null")
        if kind is None:
            kind = "object" if "properties" in schema else "string"

        if kind == "object":
            return {
                key: self.example(sub, variant, key, depth + 1)
                for key, sub in schema.get("properties", {}).items()
            }
        if kind == "array":
            count = max(1, schema.get("minItems", 1))
            item_schema = schema.get("items", {})
            values = [self.example(item_schema, variant + i, name, depth + 1) for i in range(count)]
            if schema.get("uniqueItems"):
                values = list({repr(v): v for v in values}.values())
            return values
        if kind == "integer":
            return _number(schema, variant, integer=True)
        if kind == "number":
            return _number(schema, variant, integer=False)
        if kind == "boolean":
            return variant % 2 == 0
        if kind == "null":
            return None
        return _string(schema, variant, name)

    def body(self, op: Operation, variant: int = 0) -> Any:
        schema = self.request_schema(op)
        if schema is None:
            return None
        return self.example(schema, variant)

    # --- генерация некорректных тел -----------------------------------------

    def invalid_bodies(self, op: Operation) -> Iterator[tuple[str, Any]]:
        """Тела, которые должны отклоняться валидацией (422)."""
        schema = self.request_schema(op)
        if schema is None:
            return
        base = self.body(op)
        flat = self.flatten(schema)
        if not isinstance(base, dict):
            return
        for key in flat.get("required", []):
            payload = {k: v for k, v in base.items() if k != key}
            yield f"без обязательного поля '{key}'", payload
        for key, sub in flat.get("properties", {}).items():
            for description, value in self.violations(sub):
                yield f"поле '{key}': {description}", {**base, key: value}

    def violations(self, schema: Any) -> Iterator[tuple[str, Any]]:
        schema = self.flatten(schema)
        kind = schema.get("type")
        if isinstance(kind, list):
            kind = next((k for k in kind if k != "null"), None)
        if "enum" in schema:
            yield "значение вне enum", "__not_in_enum__"
            return
        if kind in ("integer", "number"):
            if "minimum" in schema:
                yield f"меньше minimum={schema['minimum']}", schema["minimum"] - 1
            if "exclusiveMinimum" in schema and not isinstance(schema["exclusiveMinimum"], bool):
                yield f"не больше exclusiveMinimum={schema['exclusiveMinimum']}", schema["exclusiveMinimum"]
            if "maximum" in schema:
                yield f"больше maximum={schema['maximum']}", schema["maximum"] + 1
            if "exclusiveMaximum" in schema and not isinstance(schema["exclusiveMaximum"], bool):
                yield f"не меньше exclusiveMaximum={schema['exclusiveMaximum']}", schema["exclusiveMaximum"]
        if kind == "string":
            if schema.get("minLength", 0) > 0:
                yield f"короче minLength={schema['minLength']}", "x" * (schema["minLength"] - 1)
            if "maxLength" in schema:
                yield f"длиннее maxLength={schema['maxLength']}", "x" * (schema["maxLength"] + 1)
            if "pattern" in schema:
                bad = "!@# not matching ☃"
                try:
                    if not re.search(schema["pattern"], bad):
                        yield f"не подходит под pattern={schema['pattern']}", bad
                except re.error:
                    pass
        if kind == "array":
            if schema.get("minItems", 0) > 0:
                yield f"меньше minItems={schema['minItems']}", []


def _number(schema: dict, variant: int, integer: bool) -> Any:
    lo = schema.get("minimum")
    hi = schema.get("maximum")
    step = 1 if integer else 0.5
    if isinstance(schema.get("exclusiveMinimum"), (int, float)) and not isinstance(schema.get("exclusiveMinimum"), bool):
        lo = schema["exclusiveMinimum"] + step if integer else schema["exclusiveMinimum"]
    if isinstance(schema.get("exclusiveMaximum"), (int, float)) and not isinstance(schema.get("exclusiveMaximum"), bool):
        hi = schema["exclusiveMaximum"] - step if integer else schema["exclusiveMaximum"]
    if lo is not None and hi is not None:
        value = lo + (hi - lo) / 2 + variant * step
        if value >= hi:
            value = lo + (hi - lo) / 2
    elif lo is not None:
        value = lo + 1 + variant
    elif hi is not None:
        value = hi - 1 - variant
    else:
        value = 1 + variant
    multiple = schema.get("multipleOf")
    if multiple:
        value = round(value / multiple) * multiple
        if lo is not None and value < lo:
            value += multiple
    if integer:
        return int(value)
    return float(value)


_STRING_CANDIDATES = (
    "example",
    "Example",
    "example1",
    "abc",
    "ABC",
    "Abc123",
    "123",
    "+79991234567",
    "79991234567",
    "student@example.com",
    "2026-10-12",
    "12:00",
    "AB-123",
    "a1b2c3",
    "https://example.com",
)


def _string(schema: dict, variant: int, name: str) -> str:
    fmt = schema.get("format")
    if fmt == "email":
        return f"student{variant + 1}@example.com"
    if fmt == "uuid":
        return str(uuid.UUID(int=variant + 1))
    if fmt == "date-time":
        return f"2026-10-{12 + variant % 10:02d}T12:00:00Z"
    if fmt == "date":
        return f"2026-10-{12 + variant % 10:02d}"
    if fmt == "time":
        return "12:00:00"
    if fmt in ("uri", "url"):
        return f"https://example.com/{variant + 1}"
    if fmt == "ipv4":
        return f"10.0.0.{variant + 1}"

    min_len = schema.get("minLength", 0)
    max_len = schema.get("maxLength")
    pattern = schema.get("pattern")

    def fits(value: str) -> bool:
        if len(value) < min_len or (max_len is not None and len(value) > max_len):
            return False
        return not pattern or re.search(pattern, value) is not None

    base = ("example", "updated", "another")[variant % 3]
    if name:
        base = f"{base}-{name}" if not pattern else base
    candidates = [base] + list(_STRING_CANDIDATES)
    for value in candidates:
        adjusted = value
        if len(adjusted) < min_len:
            adjusted = adjusted + "x" * (min_len - len(adjusted))
        if max_len is not None and len(adjusted) > max_len:
            adjusted = adjusted[:max_len]
        if fits(adjusted):
            return adjusted
    raise SchemaError(
        f"Не удалось подобрать строку для поля '{name}' (pattern={pattern!r}). "
        "Добавьте examples=[...] в Field — CI берёт значения оттуда."
    )


def find_resources(spec: Spec) -> list[Resource]:
    ops = spec.operations()
    by_path: dict[str, dict[str, Operation]] = {}
    for op in ops:
        by_path.setdefault(op.path, {})[op.method] = op

    def normalize(segment: str) -> str:
        return segment.lower().rstrip("s")

    resources = []
    used: set[str] = set()
    for op in ops:
        if op.method != "post" or op.path_params:
            continue
        collection = op.path.rstrip("/")
        candidates = []
        for path, methods in by_path.items():
            if not {"get", "put", "delete"} <= methods.keys():
                continue
            params = PARAM_RE.findall(path)
            parent, _, last = path.rstrip("/").rpartition("/")
            if len(params) != 1 or not PARAM_RE.fullmatch(last):
                continue
            if parent == collection:
                candidates.insert(0, path)
            elif parent.rpartition("/")[0] == collection.rpartition("/")[0] and normalize(
                parent.rpartition("/")[2]
            ) == normalize(collection.rpartition("/")[2]):
                candidates.append(path)
        if not candidates or candidates[0] in used:
            continue
        item = candidates[0]
        used.add(item)
        methods = by_path[item]
        resources.append(
            Resource(
                collection=op.path,
                item=item,
                id_param=PARAM_RE.findall(item)[0],
                create=op,
                read=methods["get"],
                update=methods["put"],
                delete=methods["delete"],
            )
        )
    return resources


def extract_id(body: Any, headers: Any, id_param: str) -> Any:
    if isinstance(body, (int, str)) and not isinstance(body, bool):
        return body
    if isinstance(body, dict):
        for key in (id_param, "id", "uuid"):
            if key in body and body[key] is not None:
                return body[key]
        id_keys = [k for k in body if k.lower().endswith("id") and isinstance(body[k], (int, str))]
        if len(id_keys) == 1:
            return body[id_keys[0]]
    location = headers.get("location") if headers is not None else None
    if location:
        return location.rstrip("/").rpartition("/")[2]
    return None


def missing_id(schema: dict) -> Any:
    kind = schema.get("type")
    if kind == "integer":
        return schema.get("maximum", 987654321)
    if schema.get("format") == "uuid":
        return str(uuid.uuid4())
    return f"missing-{uuid.uuid4().hex[:12]}"
