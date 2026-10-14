"""阶段三（零成本翻译）测试：预算、降级、缓存行为。API 全部 mock，不消耗真实额度。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import translator as T  # noqa: E402


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def ok_payload(cn: str):
    return {"responseStatus": 200,
            "responseData": {"translatedText": cn, "match": 1}}


@pytest.fixture()
def tr(tmp_path, monkeypatch):
    monkeypatch.setenv("MYMEMORY_EMAIL", "")
    monkeypatch.delenv("MYMEMORY_EMAIL", raising=False)
    # 隔离数据库：用临时库
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    t = T.Translator()
    yield t
    t.close()


def test_strip_html():
    assert T.strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert T.strip_html("a &amp; b") == "a & b"


def test_chunks_short():
    assert T._chunks("abc") == ["abc"]


def test_chunks_long_splits():
    long = "这是第一句。这是第二句。" * 200
    parts = T._chunks(long)
    assert len(parts) > 1
    assert all(len(p) <= T.CHUNK_SIZE for p in parts)


def test_translate_success_and_budget(tr):
    with patch.object(T.httpx, "get",
                      return_value=FakeResp(200, ok_payload("你好世界"))) as m, \
         patch.object(T.time, "sleep"):
        got = tr.translate("Hello world")
        assert got == "你好世界"
        assert m.call_count == 1
        assert tr.budget_left() == tr.limit - len("Hello world")


def test_translate_skips_chinese(tr):
    with patch.object(T.httpx, "get") as m, patch.object(T.time, "sleep"):
        got = tr.translate("这已经是中文标题了")
        assert got == "这已经是中文标题了"
        m.assert_not_called()


def test_translate_api_warning_returns_none(tr):
    bad = {"responseStatus": 200,
           "responseData": {"translatedText":
                            "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"}}
    with patch.object(T.httpx, "get", return_value=FakeResp(200, bad)), \
         patch.object(T.time, "sleep"):
        assert tr.translate("Hello") is None


def test_translate_429_returns_none(tr):
    with patch.object(T.httpx, "get", return_value=FakeResp(429, {})), \
         patch.object(T.time, "sleep"):
        assert tr.translate("Hello") is None


def test_translate_network_error_returns_none(tr):
    with patch.object(T.httpx, "get", side_effect=RuntimeError("boom")), \
         patch.object(T.time, "sleep"):
        assert tr.translate("Hello") is None


def test_budget_exhausted_no_call(tr):
    with patch.object(T.httpx, "get") as m, patch.object(T.time, "sleep"):
        # 把预算花光
        tr.conn.execute(
            "INSERT OR REPLACE INTO translation_usage (date, chars_used) VALUES (?, ?)",
            (tr.conn.execute("SELECT 1").fetchone() and __import__("app.db", fromlist=["beijing_today"]).beijing_today(), tr.limit))
        tr.conn.commit()
        assert tr.budget_left() == 0
        assert tr.translate("Hello world, this is a test") is None
        m.assert_not_called()


def test_email_raises_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("MYMEMORY_EMAIL", "test@example.com")
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t2.db")
    t = T.Translator()
    try:
        assert t.limit == 45000
    finally:
        t.close()


def test_empty_returns_none(tr):
    with patch.object(T.httpx, "get") as m:
        assert tr.translate("") is None
        assert tr.translate(None) is None
        m.assert_not_called()
