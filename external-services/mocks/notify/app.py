"""Мок каналов уведомлений: SendGrid (email) и FCM (push). Путь на сервере: /notify.

Пути и форма запросов повторяют настоящие операции SendGrid v3 Mail Send и FCM HTTP v1
messages.send (их подмножество). Ничего никуда не отправляется: сообщения попадают во
«входящие» команды, которые видно через /inbox.
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Path, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from ..common.core import API_KEYS, ApiError, ErrorStyle, RateLimiter, create_app

DB_PATH = os.getenv("NOTIFY_DB", "/data/notify.sqlite3")
RETENTION = timedelta(days=7)
MAX_PER_TEAM = 10_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
limiter = RateLimiter(int(os.getenv("NOTIFY_RPS", "20")))


class NotifyStyle(ErrorStyle):
    """Ошибки в формате того сервиса, который мокаем."""

    def render(self, request: Request, err: ApiError):
        path = request.url.path
        if "/sendgrid/" in path:
            body = {"errors": [{"message": err.message, "field": (err.details or {}).get("field")
                                if isinstance(err.details, dict) else None, "help": None}]}
            return JSONResponse(body, status_code=err.status, headers=err.headers)
        if "/fcm/" in path:
            status = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
                      429: "RESOURCE_EXHAUSTED", 500: "INTERNAL", 503: "UNAVAILABLE"}.get(err.status, "UNKNOWN")
            fcm_code = {"UNREGISTERED": "UNREGISTERED", "RATE_LIMIT": "QUOTA_EXCEEDED",
                        "SERVICE_UNAVAILABLE": "UNAVAILABLE", "INTERNAL_ERROR": "INTERNAL"}.get(err.code, status)
            body = {"error": {"code": err.status, "message": err.message, "status": status,
                              "details": [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                                           "errorCode": fcm_code}]}}
            return JSONResponse(body, status_code=err.status, headers=err.headers)
        return super().render(request, err)


DESCRIPTION = """Мок двух провайдеров уведомлений. **Кому нужен.** Кейс «Прогноз мощности серверов»:
Alert Worker отправляет уведомление о превышении порога по email (SendGrid) и push (FCM).

Код команды пишется по настоящей документации:
[SendGrid Mail Send](https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send),
[FCM messages.send](https://firebase.google.com/docs/reference/fcm/rest/v1/projects.messages/send).
Отличия от настоящих сервисов: вместо ключа SendGrid и OAuth-токена Google в `Authorization: Bearer`
передаётся ключ команды; поддержано только подмножество полей; реальные письма и push не уходят.
Отправленное видно во «входящих» своей команды: `GET /notify/inbox` или страница `/notify/inbox/view?key=...`."""

app = create_app("Мок каналов уведомлений (SendGrid + FCM)", DESCRIPTION, style=NotifyStyle(),
                 tags=[{"name": "sendgrid", "description": "Email. Кейс: Прогноз мощности (Alert Worker)."},
                       {"name": "fcm", "description": "Push. Кейс: Прогноз мощности (Alert Worker)."},
                       {"name": "inbox", "description": "Что отправила команда: для тестов и защиты."}])

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, team TEXT NOT NULL, channel TEXT NOT NULL, created_at TEXT NOT NULL,
            recipient TEXT NOT NULL, title TEXT, body TEXT, payload TEXT NOT NULL)""")
        _conn.execute("CREATE INDEX IF NOT EXISTS ix_team_time ON messages(team, created_at)")
        _conn.commit()
    return _conn


def store(team: str, channel: str, recipient: str, title: str | None, body: str | None, payload: dict) -> str:
    mid = uuid.uuid4().hex
    t = datetime.now(timezone.utc)
    with _lock:
        c = db()
        c.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                  (mid, team, channel, t.isoformat(), recipient, title, body, json.dumps(payload, ensure_ascii=False)))
        c.execute("DELETE FROM messages WHERE created_at < ?", ((t - RETENTION).isoformat(),))
        c.execute("""DELETE FROM messages WHERE team = ? AND id NOT IN
                     (SELECT id FROM messages WHERE team = ? ORDER BY created_at DESC LIMIT ?)""",
                  (team, team, MAX_PER_TEAM))
        c.commit()
    return mid


def bearer_team(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    if not token or token not in API_KEYS:
        raise ApiError(401, "UNAUTHORIZED", "The provided authorization grant is invalid, expired, or revoked")
    team = API_KEYS[token]
    limiter.check(team)
    return team


# ---------------------------------------------------------------- SendGrid

class EmailAddress(BaseModel):
    email: str = Field(examples=["engineer@example.com"])
    name: str | None = None


class Personalization(BaseModel):
    to: list[EmailAddress] = Field(min_length=1, max_length=1000)
    cc: list[EmailAddress] | None = None
    subject: str | None = None


class Content(BaseModel):
    type: Literal["text/plain", "text/html"] = "text/plain"
    value: str = Field(min_length=1)


class MailSend(BaseModel):
    personalizations: list[Personalization] = Field(min_length=1, max_length=1000)
    from_: EmailAddress = Field(alias="from")
    subject: str | None = None
    content: list[Content] = Field(min_length=1)
    categories: list[str] | None = None
    custom_args: dict[str, str] | None = None

    model_config = {"populate_by_name": True}


@app.post("/sendgrid/v3/mail/send", tags=["sendgrid"], status_code=202,
          summary="Отправить email (как SendGrid v3 Mail Send)",
          description="Кейс Прогноз мощности: письмо инженеру о превышении порога. Ответ 202 без тела "
                      "и заголовок `X-Message-Id`, как у SendGrid.",
          responses={202: {"description": "Принято", "headers": {"X-Message-Id": {"schema": {"type": "string"}}}}})
def mail_send(body: MailSend, request: Request):
    team = bearer_team(request)
    for i, p in enumerate(body.personalizations):
        for j, a in enumerate(p.to):
            if not EMAIL_RE.match(a.email):
                raise ApiError(400, "INVALID_REQUEST", "Does not contain a valid address.",
                               details={"field": f"personalizations.{i}.to.{j}.email"})
        if not (p.subject or body.subject):
            raise ApiError(400, "INVALID_REQUEST",
                           "The subject is required. You can get around this requirement if you use a template "
                           "with a subject defined or if every personalization has a subject defined.",
                           details={"field": "subject"})
    if not EMAIL_RE.match(body.from_.email):
        raise ApiError(400, "INVALID_REQUEST", "The from email does not contain a valid address.",
                       details={"field": "from.email"})
    mid = None
    text_body = next((c.value for c in body.content if c.type == "text/plain"), body.content[0].value)
    for p in body.personalizations:
        for a in p.to:
            mid = store(team, "email", a.email, p.subject or body.subject, text_body,
                        body.model_dump(by_alias=True, exclude_none=True))
    return Response(status_code=202, headers={"X-Message-Id": mid or ""})


# ---------------------------------------------------------------- FCM

class FcmNotification(BaseModel):
    title: str | None = None
    body: str | None = None


class FcmMessage(BaseModel):
    token: str | None = Field(None, description="Токен устройства. Токены, начинающиеся с `invalid-`, считаются "
                                                 "удалёнными (404 UNREGISTERED)")
    topic: str | None = None
    notification: FcmNotification | None = None
    data: dict[str, str] | None = None


class FcmSend(BaseModel):
    validate_only: bool = False
    message: FcmMessage


class FcmSent(BaseModel):
    name: str = Field(examples=["projects/capacity-forecast/messages/0:1730550000000000%abc"])


@app.post("/fcm/v1/projects/{project_id}/messages:send", tags=["fcm"], response_model=FcmSent,
          summary="Отправить push (как FCM HTTP v1 messages.send)",
          description="Кейс Прогноз мощности: push инженеру. Нужен ровно один из `token` или `topic`. "
                      "Ответ — `name` сообщения, ошибки — в формате Google API.")
def fcm_send(body: FcmSend, request: Request, project_id: str = Path(examples=["capacity-forecast"])):
    team = bearer_team(request)
    m = body.message
    if bool(m.token) == bool(m.topic):
        raise ApiError(400, "INVALID_REQUEST", "Exactly one of token or topic must be specified")
    if m.token and m.token.startswith("invalid-"):
        raise ApiError(404, "UNREGISTERED", "Requested entity was not found.")
    if not (m.notification or m.data):
        raise ApiError(400, "INVALID_REQUEST", "Message must contain notification or data")
    mid = uuid.uuid4().hex[:16]
    if not body.validate_only:
        n = m.notification or FcmNotification()
        mid = store(team, "push", m.token or f"/topics/{m.topic}", n.title, n.body,
                    {"project": project_id, **body.model_dump(exclude_none=True)})
    return {"name": f"projects/{project_id}/messages/{mid}"}


# ---------------------------------------------------------------- входящие

class InboxItem(BaseModel):
    id: str
    channel: Literal["email", "push"]
    createdAt: datetime
    recipient: str
    title: str | None
    body: str | None
    payload: dict


class InboxPage(BaseModel):
    items: list[InboxItem]


def key_team(request: Request, key: str | None) -> str:
    k = request.headers.get("X-API-Key") or key
    auth = request.headers.get("Authorization", "")
    if not k and auth.lower().startswith("bearer "):
        k = auth[7:].strip()
    if not k or k not in API_KEYS:
        raise ApiError(401, "UNAUTHORIZED", "Нужен ключ команды: X-API-Key, Bearer или ?key=")
    return API_KEYS[k]


def fetch(team: str, channel: str | None, since: datetime | None, limit: int) -> list[dict]:
    q = "SELECT id, channel, created_at, recipient, title, body, payload FROM messages WHERE team = ?"
    args: list = [team]
    if channel:
        q += " AND channel = ?"
        args.append(channel)
    if since:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        q += " AND created_at > ?"
        args.append(since.isoformat())
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _lock:
        rows = db().execute(q, args).fetchall()
    return [{"id": r[0], "channel": r[1], "createdAt": r[2], "recipient": r[3], "title": r[4], "body": r[5],
             "payload": json.loads(r[6])} for r in rows]


@app.get("/inbox", tags=["inbox"], response_model=InboxPage, summary="Входящие команды",
         description="Сообщения, которые отправила ваша команда (по ключу), новые сверху, хранятся 7 дней.")
def inbox(request: Request, channel: Literal["email", "push"] | None = None, since: datetime | None = None,
          limit: int = Query(100, ge=1, le=1000), key: str | None = Query(None, include_in_schema=False)):
    return {"items": fetch(key_team(request, key), channel, since, limit)}


@app.delete("/inbox", tags=["inbox"], status_code=204, summary="Очистить входящие своей команды")
def inbox_clear(request: Request, key: str | None = Query(None, include_in_schema=False)):
    team = key_team(request, key)
    with _lock:
        db().execute("DELETE FROM messages WHERE team = ?", (team,))
        db().commit()
    return Response(status_code=204)


@app.get("/inbox/view", tags=["inbox"], response_class=HTMLResponse, summary="Входящие в браузере (?key=...)")
def inbox_view(request: Request, key: str | None = None, channel: Literal["email", "push"] | None = None):
    team = key_team(request, key)
    rows = fetch(team, channel, None, 200)
    trs = "".join(
        f"<tr><td>{html.escape(r['createdAt'][:19].replace('T', ' '))}</td><td>{r['channel']}</td>"
        f"<td>{html.escape(r['recipient'])}</td><td>{html.escape(r['title'] or '')}</td>"
        f"<td>{html.escape((r['body'] or '')[:300])}</td></tr>" for r in rows)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Входящие: {html.escape(team)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;margin:1rem}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}}</style></head><body>
<h1>Входящие команды {html.escape(team)}</h1><p>Последние {len(rows)} сообщений (время UTC).</p>
<table><tr><th>Время</th><th>Канал</th><th>Кому</th><th>Тема / заголовок</th><th>Текст</th></tr>{trs}</table>
</body></html>"""
