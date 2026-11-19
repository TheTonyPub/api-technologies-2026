"""Логика SOAP-клиента (сессия, повторы, пейджинг) на поддельном сервисе. Сеть и настоящий СПАРК не нужны."""
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

from _stubs import install_env, install_stubs

install_env()
install_stubs()

from lxml import etree                              # noqa: E402
from zeep.exceptions import Fault, TransportError   # noqa: E402

from app import soap_client as sc                   # noqa: E402
from app.incremental import incremental_load        # noqa: E402
from app.spark_errors import AuthFailed, SkipCompany, SparkBadRequest, SparkUnavailable  # noqa: E402
from app.store import DryRunStore                    # noqa: E402


def fault(code, message="boom"):
    detail = etree.Element("detail")
    etree.SubElement(etree.SubElement(detail, "SparkFault"), "ErrorCode").text = code
    return Fault(message, detail=detail)


class FakeSpark:
    """Поддельный сервис: проверяет SessionId из заголовка, умеет "протухать", отдаёт заготовленные ответы по операциям."""

    def __init__(self):
        self.valid, self.auth_count, self.calls, self.script, self.lock = "S1", 0, [], {}, threading.Lock()
        self.kwargs = []
        self.stale_barrier = None      # если задан: запросы с устаревшей сессией ждут друг друга перед ошибкой

    def __getitem__(self, op):
        def call(**kw):
            with self.lock:
                self.calls.append(op)
                self.kwargs.append((op, kw))
                queue = self.script.get(op)
                step = queue.pop(0) if queue else None
                if op == "Authenticate":
                    self.auth_count += 1
            if isinstance(step, Exception):
                raise step
            if op == "Authenticate":
                return {"SessionId": self.valid}
            header = kw.get("_soapheaders")
            if not header or header[0].text != self.valid:
                if self.stale_barrier is not None:
                    self.stale_barrier.wait(timeout=5)
                raise fault("SESSION_EXPIRED")
            if step is not None:
                return step
            return {"Company": {"Inn": kw.get("INN", "0"), "ShortName": "X"}}
        return call


def make_client(fake):
    client = sc.SparkClient.__new__(sc.SparkClient)
    client._local, client._auth_lock = threading.local(), threading.Lock()
    client.session_id, client.ns = None, "urn:test:spark"
    client._svc = lambda: fake
    return client


class SoapClientTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        patcher = mock.patch.object(sc.time, "sleep", lambda s: self.sleeps.append(s))
        patcher.start()
        self.addCleanup(patcher.stop)
        settings = mock.patch.multiple(sc.settings, spark_login="login", spark_password="secret",
                                       spark_page_size=0)
        settings.start()
        self.addCleanup(settings.stop)
        self.fake = FakeSpark()
        self.client = make_client(self.fake)

    def pauses(self):
        return [s for s in self.sleeps if s >= 0.5]       # мелкие паузы лимитера не считаем

    def test_login_then_call_with_session_header(self):
        data = self.client.get_company_short_report("7700000001")
        self.assertEqual(data["Company"]["Inn"], "7700000001")
        self.assertEqual(self.fake.calls, ["Authenticate", "GetCompanyShortReport"])
        op, kw = self.fake.kwargs[1]
        self.assertEqual(kw["INN"], "7700000001")
        self.assertEqual(kw["_soapheaders"][0].text, "S1")
        self.assertEqual(etree.QName(kw["_soapheaders"][0]).namespace, "urn:test:spark")
        self.assertEqual(self.fake.kwargs[0][1], {"Login": "login", "Password": "secret"})

    def test_session_expired_relogin_and_retry(self):
        self.client.get_company_short_report("7700000001")
        self.fake.valid = "S2"                             # сессия "протухла"
        self.client.get_company_short_report("7700000002")
        self.assertEqual(self.fake.auth_count, 2)
        self.assertEqual(self.client.session_id, "S2")
        self.assertEqual(self.pauses(), [])                # перелогин без пауз

    def test_auth_required_is_like_session_expired(self):
        self.fake.script["GetCompanyShortReport"] = [fault("AUTH_REQUIRED")]
        self.client.get_company_short_report("7700000001")
        self.assertEqual(self.fake.auth_count, 2)

    def test_auth_failed_is_loud_and_not_retried(self):
        self.fake.script["Authenticate"] = [fault("AUTH_FAILED")]
        with self.assertRaises(AuthFailed):
            self.client.authenticate()
        self.assertEqual(self.fake.calls, ["Authenticate"])
        self.assertEqual(self.pauses(), [])

    def test_company_not_found_is_skip(self):
        self.fake.script["GetCompanyShortReport"] = [fault("COMPANY_NOT_FOUND")]
        with self.assertRaises(SkipCompany) as ctx:
            self.client.get_company_short_report("7700000001")
        self.assertIn("7700000001", str(ctx.exception))
        self.assertEqual(self.fake.calls.count("GetCompanyShortReport"), 1)

    def test_invalid_request_fails_fast(self):
        self.fake.script["GetCompanyList"] = [fault("INVALID_REQUEST")]
        with self.assertRaises(SparkBadRequest) as ctx:
            self.client.get_company_list(1)
        self.assertIn("GetCompanyList", str(ctx.exception))
        self.assertEqual(self.fake.calls.count("GetCompanyList"), 1)    # без 6 повторов
        self.assertEqual(self.pauses(), [])

    def test_rate_limit_backoff_then_success(self):
        self.fake.script["GetCompanyShortReport"] = [fault("RATE_LIMIT"), fault("RATE_LIMIT")]
        self.client.get_company_short_report("7700000001")
        self.assertEqual(self.pauses(), [1, 2])

    def test_retry_after_header_is_respected(self):
        self.fake.script["GetCompanyShortReport"] = [sc.RetryLater(429, "7")]
        self.client.get_company_short_report("7700000001")
        self.assertEqual(self.pauses(), [7.0])

    def test_retry_after_survives_the_course_mock_soap_fault_status(self):
        response = mock.Mock(status_code=500, headers={"Retry-After": "5"})
        transport = sc._Transport.__new__(sc._Transport)
        with mock.patch.object(sc.Transport, "post", return_value=response, create=True):
            with self.assertRaises(sc.RetryLater) as caught:
                transport.post("http://spark/ws", b"", {})

        self.assertEqual(sc.pause_for(caught.exception, 0), 5.0)

    def test_gives_up_without_useless_last_sleep(self):
        self.fake.script["GetCompanyShortReport"] = [TransportError("500")] * sc.MAX_ATTEMPTS
        with self.assertRaises(SparkUnavailable) as ctx:
            self.client.get_company_short_report("7700000001")
        self.assertIn("7700000001", str(ctx.exception))
        self.assertEqual(self.pauses(), [1, 2, 4, 8, 16])   # 5 пауз на 6 попыток, после последней не спим

    def test_fault_code_from_message_when_no_detail(self):
        self.assertEqual(sc.fault_code(Fault("Session SESSION_EXPIRED, login again")), "SESSION_EXPIRED")
        self.assertEqual(sc.fault_code(Fault("что-то странное")), "FAULT")

    def test_threads_share_one_relogin(self):
        self.client.get_company_short_report("7700000001")
        self.fake.valid = "S2"
        self.fake.stale_barrier = threading.Barrier(8)     # все 8 потоков одновременно увидят протухшую сессию
        barrier, errors = threading.Barrier(8), []

        def work(i):
            try:
                barrier.wait()
                self.client.get_company_short_report(f"77000000{i:02d}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.fake.auth_count, 2)           # первый вход + ОДИН перелогин на все потоки

    # ---------- пейджинг списка компаний ----------

    @staticmethod
    def page(*inns, total=None):
        d = {"Page": 1, "Companies": {"Company": [{"INN": i, "ShortName": "X", "Status": "ACTIVE"} for i in inns]}}
        if total is not None:
            d["Total"] = total
        return d

    @staticmethod
    def changes(*pairs, total=None):
        d = {"Page": 1, "Changes": {"Change": [{"INN": i, "ChangedAt": "2026-11-10 10:09:45+00:00", "ChangeType": t}
                                              for i, t in pairs]}}
        if total is not None:
            d["Total"] = total
        return d

    def test_list_stops_when_server_repeats_last_page(self):
        same = self.page("7700000001", "7700000002")
        self.fake.script["GetCompanyList"] = [same] * 50
        self.assertEqual(self.client.get_all_inns(), ["7700000001", "7700000002"])
        self.assertEqual(self.fake.calls.count("GetCompanyList"), 2)    # вторая страница ничего нового не принесла

    def test_list_stops_by_total(self):
        self.fake.script["GetCompanyList"] = [self.page("7700000001", total=3), self.page("7700000002", total=3),
                                              self.page("7700000003", total=3), self.page("7700000004", total=3)]
        self.assertEqual(len(self.client.get_all_inns()), 3)
        self.assertEqual(self.fake.calls.count("GetCompanyList"), 3)    # Total=3 набрали на третьей странице

    def test_list_real_shape_ten_pages_of_hundred(self):
        pages = [self.page(*[f"{p:02d}{i:08d}"[:10] for i in range(100)], total=1000) for p in range(1, 11)]
        pages.append(self.page("9999999999", total=1000))
        self.fake.script["GetCompanyList"] = pages
        self.assertEqual(len(self.client.get_all_inns()), 1000)
        self.assertEqual(self.fake.calls.count("GetCompanyList"), 10)   # лишней одиннадцатой страницы нет
        self.assertEqual([kw.get("Page") for op, kw in self.fake.kwargs if op == "GetCompanyList"], list(range(1, 11)))

    def test_list_stops_on_empty_page(self):
        self.fake.script["GetCompanyList"] = [self.page("7700000001"), {"Companies": []}]
        self.assertEqual(self.client.get_all_inns(), ["7700000001"])

    def test_list_rejects_empty_page_before_total(self):
        self.fake.script["GetCompanyList"] = [
            self.page("7700000001", total=2), {"Companies": []},
        ]
        with self.assertRaises(SparkUnavailable):
            self.client.get_all_inns()

    def test_list_rejects_exhausted_page_limit(self):
        self.fake.script["GetCompanyList"] = [self.page("7700000001")]
        with self.assertRaises(SparkUnavailable):
            self.client.get_all_inns(max_pages=1)

    def test_page_size_is_sent_only_when_configured(self):
        self.fake.script["GetCompanyList"] = [self.page("7700000001", total=1)]
        self.client.get_all_inns()
        self.assertNotIn("PageSize", self.fake.kwargs[-1][1])
        old = sc.settings.spark_page_size
        sc.settings.spark_page_size = 50
        try:
            self.fake.script["GetCompanyList"] = [self.page("7700000001", total=1)]
            self.client.get_all_inns()
            self.assertEqual(self.fake.kwargs[-1][1]["PageSize"], 50)
        finally:
            sc.settings.spark_page_size = old

    def test_list_without_page_parameter(self):
        self.fake.script["GetCompanyList"] = [TypeError("got an unexpected keyword argument 'Page'"),
                                              self.page("7700000001", "7700000002")]
        self.assertEqual(self.client.get_all_inns(), ["7700000001", "7700000002"])
        self.assertNotIn("Page", self.fake.kwargs[-1][1])

    def test_other_type_errors_are_not_hidden(self):
        self.fake.script["GetCompanyList"] = [TypeError("совсем другая ошибка")]
        with self.assertRaises(TypeError):
            self.client.get_all_inns()

    def test_changed_follows_pages_and_counts_changes_not_companies(self):
        """Total = число изменений; у одной компании их может быть несколько, ИНН в итоге уникальные."""
        self.fake.script["GetChangedCompanies"] = [
            self.changes(("7700000001", "head"), ("7700000002", "address"), total=4),
            self.changes(("7700000001", "status"), ("7700000003", "group"), total=4),
            self.changes(("7700000009", "head"), total=4)]       # третью страницу просить не должны
        since = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertEqual(self.client.get_changed_companies(since), ["7700000001", "7700000002", "7700000003"])
        calls = [kw for op, kw in self.fake.kwargs if op == "GetChangedCompanies"]
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["Page"] for c in calls], [1, 2])
        self.assertTrue(all(c["Since"] == since for c in calls))

    def test_repeated_change_page_does_not_advance_cursor(self):
        since = datetime(2026, 11, 10, tzinfo=timezone.utc).isoformat()
        for total in (2, None):
            with self.subTest(total=total):
                page = self.changes(("7700000001", "head"), total=total)
                self.fake.script["GetChangedCompanies"] = [page, page]
                store = DryRunStore()
                store.set_state("last_sync_at", since)
                with self.assertRaises(SparkUnavailable):
                    incremental_load(self.client, store)
                self.assertEqual(store.get_state("last_sync_at"), since)
                self.assertEqual(store.current_inns(), set())


if __name__ == "__main__":
    unittest.main()
