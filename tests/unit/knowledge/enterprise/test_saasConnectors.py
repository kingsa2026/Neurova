# -*- coding: utf-8 -*-
"""U-conn 扩展批：SaaS REST 六连接器（bigquery/databricks/salesforce/
servicenow/looker/airflow）——registry 分派、fetchBatch 形状与游标、
health 探测、干跑保真回归（http_pull/unity_catalog 真实 url 可过编译期校验）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from neurova.knowledge.enterprise.connectors_saas import (
    AirflowAdapter,
    BigQueryAdapter,
    DatabricksAdapter,
    LookerAdapter,
    SalesforceAdapter,
    ServiceNowAdapter,
    SAAS_ADAPTERS,
)
from neurova.knowledge.enterprise.registry import buildAdapter
from neurova.knowledge.enterprise.schema_mapping import (
    VARIANT_CLOSED_SETS,
    validateDescriptor,
)


class FakeHttpxResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    @property
    def status(self):
        """safe_fetch 终态响应口径（实现改走 safe_fetch 后同名可用）。"""
        return self.status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)


def _patchSafeFetch(monkeypatch, mod, fakeGet=None, fakePost=None):
    """实现出站统一走 safe_fetch 后，把 httpx 形态的旧 fake 适配到新通路。

    safe_fetch(url, method=..., headers=..., data=..., timeout=...)：
    GET 的查询串编在 URL 里；POST 的 JSON 体/表单体都在 data 字节。
    """
    import urllib.parse

    def fake_safe_fetch(url, *, method="GET", headers=None, data=None,
                        timeout=None, max_bytes=None):
        if method == "POST":
            if fakePost is None:
                raise AssertionError("unexpected POST %s" % url)
            raw = (data or b"").decode("utf-8")
            try:
                body = json.loads(raw) if raw else None
            except Exception:
                body = None
            if body is not None:
                return fakePost(url, headers=headers, json=body, timeout=timeout)
            return fakePost(url, headers=headers,
                            data=dict(urllib.parse.parse_qsl(raw)), timeout=timeout)
        if fakeGet is None:
            raise AssertionError("unexpected GET %s" % url)
        parsed = urllib.parse.urlparse(url)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        return fakeGet(url.split("?", 1)[0], headers=headers, params=params,
                       timeout=timeout)

    monkeypatch.setattr(mod, "safe_fetch", fake_safe_fetch)


def _run(coro):
    return asyncio.run(coro)


class TestRegistryDispatch:
    def test_sixSaasKindsDispatchToTheirAdapters(self):
        for sourceType, adapterClass in SAAS_ADAPTERS.items():
            adapter = buildAdapter({"sourceType": sourceType,
                                    "base_url": "https://saas.example"},
                                   "src-1", "default")
            assert type(adapter).__name__ == adapterClass.__name__

    def test_cassandraAndGitDispatch(self):
        from neurova.knowledge.enterprise.connectors_git import GitAdapter
        from neurova.knowledge.enterprise.connectors_nosql import CassandraAdapter

        cassandra = buildAdapter({"sourceType": "cassandra",
                                  "contact_points": "127.0.0.1"},
                                 "src-cas", "default")
        git = buildAdapter({"sourceType": "git", "repo_url": "/tmp/repo"},
                           "src-git", "default")
        assert isinstance(cassandra, CassandraAdapter)
        assert isinstance(git, GitAdapter)

    @pytest.mark.parametrize("sourceType", list(SAAS_ADAPTERS))
    def test_missingRequiredConfigRaisesInsteadOfEmptySuccess(self, sourceType):
        adapter = buildAdapter({"sourceType": sourceType}, "saas-missing", "default")
        with pytest.raises(ValueError):
            _run(adapter.fetchBatch(None, 10))

    def test_fullPageWithoutNextTokenDoesNotLoop(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = DatabricksAdapter(
            {"sourceType": "databricks", "base_url": "https://dbx.example",
             "warehouse_id": "wh-1", "query": "SELECT id FROM t",
             "columns": ["id"]}, "dbx-page", "default")

        def fakePost(url, headers=None, json=None, timeout=None):
            return FakeHttpxResponse({
                "status": {"state": "SUCCEEDED"},
                "result": {"data_array": [["1"], ["2"]]}})

        _patchSafeFetch(monkeypatch, mod, fakePost=fakePost)
        batch = _run(adapter.fetchBatch(None, 2))
        assert len(batch.rows) == 2
        assert batch.hasMore is False
        assert batch.nextCursor is None

    def test_variantRegression_realUrlsPassCompileGate(self):
        """修正回归：http_pull/unity_catalog 真实 url 曾被 kind 名闭集误拒。"""
        httpPull = {"sourceType": "http_pull", "url": "https://x.example/rows",
                    "columns": ["id"],
                    "subject": {"template": "{id}"},
                    "predicate": {"termId": "linked"},
                    "object": {"column": "id", "kind": "column"}}
        unity = {"sourceType": "unity_catalog", "base_url": "https://uc.example",
                 "table": "t", "columns": ["id"],
                 "subject": {"template": "{id}"},
                 "predicate": {"termId": "linked"},
                 "object": {"column": "id", "kind": "column"}}
        validateDescriptor(httpPull, None)
        validateDescriptor(unity, None)
        assert "http_pull" not in VARIANT_CLOSED_SETS
        assert "unity_catalog" not in VARIANT_CLOSED_SETS


class TestBigQueryAdapter:
    def test_fetchFlattensfvAndCarriesPageToken(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = BigQueryAdapter(
            {"sourceType": "bigquery", "project_id": "proj-1",
             "query": "SELECT id, city FROM orders",
             "credential_env": "T_BQ"}, "bq1", "default")
        monkeypatch.setenv("T_BQ", "tok-bq")
        seen = {}

        def fakePost(url, headers=None, json=None, timeout=None):
            seen["url"] = url
            seen["body"] = json
            return FakeHttpxResponse({
                "schema": {"fields": [{"name": "id"}, {"name": "city"}]},
                "rows": [{"f": [{"v": "1"}, {"v": "shanghai"}]},
                         {"f": [{"v": "2"}, {"v": "beijing"}]}],
                "pageToken": "PAGE-2"})

        _patchSafeFetch(monkeypatch, mod, fakePost=fakePost)
        batch = _run(adapter.fetchBatch(None, 100))
        assert "projects/proj-1/queries" in seen["url"]
        assert seen["body"]["query"] == "SELECT id, city FROM orders"
        assert batch.rows == [{"id": "1", "city": "shanghai"},
                              {"id": "2", "city": "beijing"}]
        assert batch.hasMore is True
        assert batch.nextCursor.token == "PAGE-2"

    def test_fetchFailureRaisesInsteadOfEmptySuccess(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = BigQueryAdapter(
            {"sourceType": "bigquery", "project_id": "proj-1",
             "query": "SELECT id FROM orders"}, "bq-fail", "default")

        def boom(*args, **kwargs):
            raise ConnectionError("upstream unavailable")

        monkeypatch.setattr(mod, "safe_fetch", boom)
        with pytest.raises(ConnectionError, match="upstream unavailable"):
            _run(adapter.fetchBatch(None, 10))

    def test_missingProjectRaisesInsteadOfEmptySuccess(self):
        adapter = BigQueryAdapter({"sourceType": "bigquery",
                                   "base_url": "https://bq.example"},
                                  "bq2", "default")
        with pytest.raises(ValueError, match="project_id"):
            _run(adapter.fetchBatch(None, 10))


class TestDatabricksAdapter:
    def test_fetchFlattensDataArrayByColumns(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = DatabricksAdapter(
            {"sourceType": "databricks", "base_url": "https://dbx.example",
             "warehouse_id": "wh-1", "query": "SELECT id FROM t",
             "columns": ["id", "city"], "credential_env": "T_DBX"},
            "dbx1", "default")
        monkeypatch.setenv("T_DBX", "tok-dbx")
        seen = {}

        def fakePost(url, headers=None, json=None, timeout=None):
            seen["body"] = json
            return FakeHttpxResponse({
                "status": {"state": "SUCCEEDED"},
                "result": {"data_array": [["1", "shanghai"], ["2", "beijing"]]}})

        _patchSafeFetch(monkeypatch, mod, fakePost=fakePost)
        batch = _run(adapter.fetchBatch(None, 100))
        assert seen["body"]["warehouse_id"] == "wh-1"
        assert batch.rows == [{"id": "1", "city": "shanghai"},
                              {"id": "2", "city": "beijing"}]
        assert batch.hasMore is False


class TestSalesforceAdapter:
    def test_firstPageThenNextRecordsUrlCursor(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = SalesforceAdapter(
            {"sourceType": "salesforce", "base_url": "https://sf.example",
             "soql": "SELECT Id FROM Account", "credential_env": "T_SF"},
            "sf1", "default")
        monkeypatch.setenv("T_SF", "tok-sf")
        calls = []

        def fakeGet(url, headers=None, params=None, timeout=None):
            calls.append(url)
            if len(calls) == 1:
                return FakeHttpxResponse({
                    "records": [{"attributes": {"type": "Account"}, "Id": "1"},
                                {"attributes": {"type": "Account"}, "Id": "2"}],
                    "nextRecordsUrl": "/services/data/v59.0/query/02"})
            return FakeHttpxResponse({
                "records": [{"attributes": {"type": "Account"}, "Id": "3"}],
                "done": True})

        _patchSafeFetch(monkeypatch, mod, fakeGet=fakeGet)
        batch = _run(adapter.fetchBatch(None, 100))
        assert "services/data/v59.0/query" in calls[0]
        assert batch.rows == [{"Id": "1"}, {"Id": "2"}]
        assert batch.hasMore is True
        batch2 = _run(adapter.fetchBatch(batch.nextCursor, 100))
        assert calls[1].endswith("/services/data/v59.0/query/02")
        assert batch2.rows == [{"Id": "3"}]
        assert batch2.hasMore is False


class TestServiceNowAdapter:
    def test_offsetPaginationWithBasicAuth(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = ServiceNowAdapter(
            {"sourceType": "servicenow", "base_url": "https://sn.example",
             "table": "incident", "credentialEnv": {"username": "T_SN_USER",
                                                    "password": "T_SN_PASS"}},
            "sn1", "default")
        monkeypatch.setenv("T_SN_USER", "admin")
        monkeypatch.setenv("T_SN_PASS", "secret")
        seen = []

        def fakeGet(url, headers=None, params=None, timeout=None):
            seen.append((url, params, headers.get("Authorization")))
            offset = int((params or {}).get("sysparm_offset", 0))
            if offset >= 4:
                return FakeHttpxResponse({"result": []})
            rows = [{"number": "INC%07d" % (offset + i + 1)}
                    for i in range(min(2, 4 - offset))]
            return FakeHttpxResponse({"result": rows})

        _patchSafeFetch(monkeypatch, mod, fakeGet=fakeGet)
        batch = _run(adapter.fetchBatch(None, 2))
        assert batch.rows[0]["number"] == "INC0000001"
        assert batch.hasMore is True
        batch2 = _run(adapter.fetchBatch(batch.nextCursor, 2))
        assert batch2.rows[0]["number"] == "INC0000003"
        # 恰好取满 limit 视为「可能还有」（ERP 族同款语义），下一批收束
        assert batch2.hasMore is True
        batch3 = _run(adapter.fetchBatch(batch2.nextCursor, 2))
        assert batch3.rows == [] and batch3.hasMore is False
        assert seen[0][2] is not None, "basic auth 凭据应进 Authorization 头"


class TestLookerAdapter:
    def test_loginThenRunJson(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = LookerAdapter(
            {"sourceType": "looker", "base_url": "https://lk.example",
             "query_id": "42",
             "credentialEnv": {"client_id": "T_LK_ID", "client_secret": "T_LK_SECRET"}},
            "lk1", "default")
        monkeypatch.setenv("T_LK_ID", "cid")
        monkeypatch.setenv("T_LK_SECRET", "csecret")
        calls = []

        def fakePost(url, headers=None, data=None, json=None, timeout=None):
            calls.append(("POST", url))
            assert data["client_id"] == "cid" and data["client_secret"] == "csecret"
            return FakeHttpxResponse({"access_token": "lk-token"})

        def fakeGet(url, headers=None, params=None, timeout=None):
            calls.append(("GET", url))
            assert headers["Authorization"] == "Bearer lk-token"
            return FakeHttpxResponse([{"city": "shanghai"}, {"city": "beijing"}])

        _patchSafeFetch(monkeypatch, mod, fakeGet=fakeGet, fakePost=fakePost)
        batch = _run(adapter.fetchBatch(None, 100))
        assert any(u[1].endswith("/login") for u in calls)
        assert any(u[1].endswith("/queries/42/run/json") for u in calls)
        assert batch.rows == [{"city": "shanghai"}, {"city": "beijing"}]
        assert batch.hasMore is False


class TestAirflowAdapter:
    def test_dagRunsOffsetPagination(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = AirflowAdapter(
            {"sourceType": "airflow", "base_url": "https://af.example",
             "dag_id": "daily_etl",
             "credentialEnv": {"username": "T_AF_USER", "password": "T_AF_PASS"}},
            "af1", "default")
        monkeypatch.setenv("T_AF_USER", "afuser")
        monkeypatch.setenv("T_AF_PASS", "afpass")
        seen = []

        def fakeGet(url, headers=None, params=None, timeout=None):
            seen.append(params)
            offset = int((params or {}).get("offset", 0))
            rows = [{"dag_run_id": "run%d" % (offset + i + 1),
                     "state": "success"} for i in range(2)]
            return FakeHttpxResponse({"dag_runs": rows, "total_entries": 4})

        _patchSafeFetch(monkeypatch, mod, fakeGet=fakeGet)
        batch = _run(adapter.fetchBatch(None, 2))
        assert batch.rows[0]["dag_run_id"] == "run1"
        assert batch.hasMore is True
        batch2 = _run(adapter.fetchBatch(batch.nextCursor, 2))
        assert batch2.rows[0]["dag_run_id"] == "run3"
        assert batch2.hasMore is True


class TestHealthProbe:
    def test_healthProbesBaseWithToken(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_saas as mod

        adapter = BigQueryAdapter(
            {"sourceType": "bigquery", "base_url": "https://bq.example",
             "project_id": "p", "query": "q", "credential_env": "T_BQ_H"},
            "bq9", "default")
        monkeypatch.setenv("T_BQ_H", "tok")
        _patchSafeFetch(monkeypatch, mod, fakeGet=lambda *a, **kw: FakeHttpxResponse({}))
        health = _run(adapter.health())
        assert health.status == "ok"

    def test_healthWithoutBaseIsError(self):
        """无 base_url 且无缺省基址的族（ServiceNow）→ error 而非降级探测。"""
        adapter = ServiceNowAdapter({"sourceType": "servicenow",
                                     "table": "incident"},
                                    "sn9", "default")
        health = _run(adapter.health())
        assert health.status == "error"
