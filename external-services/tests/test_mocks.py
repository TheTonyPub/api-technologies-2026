import os
import tempfile

os.environ.setdefault("MOCK_API_KEYS", "capacity:k-cap,antifraud:k-af,spark:k-sp")
os.environ.setdefault("SPARK_USERS", "spark:spark-team:secret")
os.environ.setdefault("SPARK_LATENCY", "off")
os.environ.setdefault("CLIENT_DATA_LATENCY", "off")
os.environ.setdefault("NOTIFY_DB", os.path.join(tempfile.mkdtemp(), "n.sqlite3"))

from fastapi.testclient import TestClient  # noqa: E402
from lxml import etree  # noqa: E402

from mocks.abs.app import app as abs_app  # noqa: E402
from mocks.client_data.app import app as cd_app  # noqa: E402
from mocks.common import companies  # noqa: E402
from mocks.monitoring.app import app as mon_app  # noqa: E402
from mocks.notify.app import app as notify_app  # noqa: E402
from mocks.spark.app import app as spark_app  # noqa: E402

H = {"X-API-Key": "k-af"}


def test_auth_and_scenarios():
    c = TestClient(abs_app)
    assert c.get("/health").status_code == 200
    r = c.get("/v1/clients")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"
    assert c.get("/v1/clients", headers={**H, "X-Mock-Scenario": "unavailable"}).status_code == 503
    r = c.get("/v1/clients", headers={**H, "X-Request-Id": "abc"})
    assert r.headers["X-Request-Id"] == "abc"


def test_abs():
    c = TestClient(abs_app)
    r = c.get("/v1/clients", headers=H, params={"limit": 2})
    assert r.status_code == 200 and len(r.json()["items"]) == 2 and r.json()["nextCursor"] == "2"
    assert c.get("/v1/clients/cl-000001", headers=H).json()["accounts"]
    acc = c.get("/v1/accounts/acc-0000001", headers=H).json()
    assert acc["client_id"] == "cl-000001"
    r = c.get("/v1/transactions", headers=H, params={"limit": 500})
    body = r.json()
    assert r.status_code == 200 and len(body["items"]) == 500 and body["nextCursor"]
    r2 = c.get("/v1/transactions", headers=H, params={"limit": 500, "cursor": body["nextCursor"]})
    ids1 = {x["transaction_id"] for x in body["items"]}
    assert not ids1 & {x["transaction_id"] for x in r2.json()["items"]}
    tx = body["items"][0]
    lab = c.get(f"/v1/transactions/{tx['transaction_id']}/label", headers=H).json()
    assert lab["is_fraud"] == tx["is_fraud"]
    live = c.get("/v1/transactions/live", headers=H, params={"limit": 10}).json()
    assert live["items"] and "is_fraud" not in live["items"][0]
    nxt = c.get("/v1/transactions/live", headers=H, params={"after": live["nextCursor"]}).json()
    assert not {x["transaction_id"] for x in live["items"]} & {x["transaction_id"] for x in nxt["items"]}
    r = c.get(f"/v1/transactions/{live['items'][-1]['transaction_id']}/label", headers=H)
    assert r.status_code == 404 and r.json()["code"] == "LABEL_NOT_READY"
    # юрлица
    flags = companies.bank_client_flags()
    cs = companies.universe()[0]
    client_inn = next(x.inn for x in cs if flags[x.idx])
    other_inn = next(x.inn for x in cs if not flags[x.idx])
    assert c.get(f"/v1/legal-clients/{client_inn}", headers=H).status_code == 200
    assert c.get(f"/v1/legal-clients/{other_inn}", headers=H).json()["code"] == "NOT_A_CLIENT"
    lk = c.post("/v1/legal-clients:lookup", headers=H, json={"inns": [client_inn, other_inn]}).json()
    assert [x["is_bank_client"] for x in lk["items"]] == [True, False]
    import datetime as dt
    y = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).date() - dt.timedelta(days=1)
    r = c.get(f"/v1/exports/transactions/{y}", headers=H)
    assert r.status_code == 200 and len(r.text.splitlines()) > 1000


def test_client_data():
    c = TestClient(cd_app)
    r = c.get("/v1/persons/cl-000001", headers=H)
    assert r.status_code in (200, 404)
    b = c.post("/v1/persons:batch", headers=H, json={"client_ids": [f"cl-{i:06d}" for i in range(1, 51)]}).json()
    assert len(b["items"]) + len(b["not_found"]) == 50
    assert c.get("/v1/regions/77/risk", headers=H).json()["risk_category"] == "low"
    assert len(c.get("/v1/regions", headers=H).json()) == 25
    m = c.get("/v1/merchants/m-00001/risk", headers=H)
    assert m.status_code == 200 and "X-RateLimit-Remaining" in m.headers
    assert len(c.get("/v1/merchants/risk", headers=H, params={"limit": 500}).json()["items"]) == 500


def soap(body: str, sid: str | None = None) -> str:
    header = f"<soap:Header><spk:SessionId>{sid}</spk:SessionId></soap:Header>" if sid else ""
    return ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:spk="urn:mock:spark:v1">'
            f"{header}<soap:Body>{body}</soap:Body></soap:Envelope>")


NS = {"soap": "http://schemas.xmlsoap.org/soap/envelope/", "spk": "urn:mock:spark:v1"}


def test_spark():
    c = TestClient(spark_app)
    w = c.get("/ws?wsdl")
    assert w.status_code == 200 and b"SparkService" in w.content
    etree.fromstring(w.content)
    r = c.post("/ws", content=soap('<spk:GetCompanyShortReport><spk:INN>1</spk:INN></spk:GetCompanyShortReport>'))
    assert r.status_code == 500 and b"AUTH_REQUIRED" in r.content
    r = c.post("/ws", content=soap("<spk:Authenticate><spk:Login>spark-team</spk:Login>"
                                   "<spk:Password>secret</spk:Password></spk:Authenticate>"))
    sid = etree.fromstring(r.content).find(".//spk:SessionId", NS).text
    inn = companies.universe()[0][0].inn
    r = c.post("/ws", content=soap(f"<spk:GetCompanyShortReport><spk:INN>{inn}</spk:INN></spk:GetCompanyShortReport>", sid))
    assert r.status_code == 200 and etree.fromstring(r.content).find(".//spk:OGRN", NS) is not None
    r = c.post("/ws", content=soap("<spk:GetCompanyShortReport><spk:INN>1234567890</spk:INN></spk:GetCompanyShortReport>", sid))
    assert b"INVALID_INN" in r.content
    grouped = next(x for x in companies.universe()[0] if x.group_id)
    r = c.post("/ws", content=soap(f"<spk:GetCompanyGroup><spk:INN>{grouped.inn}</spk:INN></spk:GetCompanyGroup>", sid))
    assert r.status_code == 200
    r = c.post("/ws", content=soap("<spk:GetCompanyList><spk:PageSize>500</spk:PageSize></spk:GetCompanyList>", sid))
    assert len(etree.fromstring(r.content).findall(".//spk:Company", NS)) == 500
    import datetime as dt
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = c.post("/ws", content=soap(f"<spk:GetChangedCompanies><spk:Since>{since}</spk:Since></spk:GetChangedCompanies>", sid))
    assert int(etree.fromstring(r.content).find(".//spk:Total", NS).text) > 50
    r = c.post("/ws", content=soap("<spk:Nope/>", sid))
    assert b"UNKNOWN_OPERATION" in r.content
    assert c.get("/").status_code == 200


def test_monitoring():
    c = TestClient(mon_app)
    h = {"X-API-Key": "k-cap"}
    assert len(c.get("/v1/servers", headers=h).json()) == 40
    assert len(c.get("/v1/information-systems", headers=h).json()) == 8
    r = c.get("/v1/servers/srv-001/metrics/current", headers=h)
    assert r.status_code in (200, 503)
    assert c.get("/v1/servers/srv-013/metrics/current", headers=h).json()["code"] == "SERVER_OFFLINE"
    import datetime as dt
    frm = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)).isoformat()
    r = c.get("/v1/servers/srv-004/metrics", headers=h, params={"from": frm, "step": "1d"})
    pts = r.json()["points"]
    assert r.status_code == 200 and 360 <= len(pts) <= 367
    assert pts[-1]["diskPercent"] > pts[0]["diskPercent"]
    assert c.get("/v1/servers/srv-004/metrics", headers=h, params={"from": frm, "step": "1m"}).status_code == 400


def test_notify():
    c = TestClient(notify_app)
    h = {"Authorization": "Bearer k-cap"}
    mail = {"personalizations": [{"to": [{"email": "eng@example.com"}]}], "from": {"email": "alerts@example.com"},
            "subject": "CPU > 80%", "content": [{"type": "text/plain", "value": "srv-009"}]}
    r = c.post("/sendgrid/v3/mail/send", headers=h, json=mail)
    assert r.status_code == 202 and r.headers["X-Message-Id"]
    assert c.post("/sendgrid/v3/mail/send", json=mail).json()["errors"][0]["message"]
    bad = {**mail, "personalizations": [{"to": [{"email": "nope"}]}]}
    assert c.post("/sendgrid/v3/mail/send", headers=h, json=bad).json()["errors"][0]["field"].endswith("email")
    r = c.post("/fcm/v1/projects/p1/messages:send", headers=h,
               json={"message": {"token": "abc", "notification": {"title": "t", "body": "b"}}})
    assert r.status_code == 200 and r.json()["name"].startswith("projects/p1/messages/")
    r = c.post("/fcm/v1/projects/p1/messages:send", headers=h, json={"message": {"token": "invalid-1", "data": {"a": "b"}}})
    assert r.status_code == 404 and r.json()["error"]["details"][0]["errorCode"] == "UNREGISTERED"
    items = c.get("/inbox", headers={"X-API-Key": "k-cap"}).json()["items"]
    assert {i["channel"] for i in items} == {"email", "push"}
    assert c.get("/inbox", headers={"X-API-Key": "k-af"}).json()["items"] == []
    assert c.get("/inbox/view", params={"key": "k-cap"}).status_code == 200
    assert c.delete("/inbox", headers={"X-API-Key": "k-cap"}).status_code == 204
