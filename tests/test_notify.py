"""阶段五测试：通知渠道（默认关闭）与日报格式化。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import notify


def test_notify_disabled_by_default():
    os.environ.pop("NOTIFY_ENABLED", None)
    assert notify.is_enabled() is False
    results = notify.send_report("t", "b")
    assert "skipped" in results


def test_notify_status_has_no_secrets():
    s = notify.status()
    assert "enabled" in s and "channel" in s
    blob = str(s)
    assert "SMTP_PASS" not in blob and "TELEGRAM_BOT_TOKEN" not in blob


def test_email_fails_gracefully_without_config():
    os.environ.pop("SMTP_HOST", None)
    ok, msg = notify.send_email("t", "b")
    assert ok is False and "未配置" in msg


def test_telegram_fails_gracefully_without_config():
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    ok, msg = notify.send_telegram("hi")
    assert ok is False and "未配置" in msg


def test_format_report():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import push_report
    d = {"date": "2026-10-14", "hot_summary": "摘要",
         "hot": [{"title": "T1", "url": "https://e.com/1", "source": "hn",
                  "score": 73.0}],
         "opportunities": [{"title": "O1", "url": "https://e.com/2",
                            "source": "hn", "score": 64.0}],
         "last_run": {"started_at": "2026-10-14 22:00",
                      "status": "partial", "new_items": 10}}
    text = push_report.format_report(d)
    assert "2026-10-14" in text and "T1" in text and "O1" in text
    assert "https://e.com/1" in text


if __name__ == "__main__":
    test_notify_disabled_by_default()
    test_notify_status_has_no_secrets()
    test_email_fails_gracefully_without_config()
    test_telegram_fails_gracefully_without_config()
    test_format_report()
    print("通知测试 5 项通过 ✓")
