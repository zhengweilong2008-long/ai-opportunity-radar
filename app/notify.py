"""通知渠道：邮件 / Telegram（可配置，默认全部关闭）。

配置（环境变量，见 .env.example）：
    NOTIFY_ENABLED=false
    NOTIFY_CHANNEL=email          # email / telegram / both
    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / NOTIFY_TO
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID

设计原则：默认不开启、不产生费用；发送失败只记录不中断主流程。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

import httpx


def is_enabled() -> bool:
    return os.environ.get("NOTIFY_ENABLED", "false").lower() == "true"


def channel() -> str:
    return os.environ.get("NOTIFY_CHANNEL", "email").lower()


def status() -> dict:
    """供状态页展示的通知配置状态（不含密钥）。"""
    ch = channel()
    cfg = {
        "enabled": is_enabled(),
        "channel": ch,
        "email_configured": bool(os.environ.get("SMTP_HOST")
                                 and os.environ.get("NOTIFY_TO")),
        "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN")
                                    and os.environ.get("TELEGRAM_CHAT_ID")),
    }
    return cfg


def send_email(subject: str, body: str) -> tuple[bool, str]:
    """SMTP 发送。返回 (成功, 说明)。"""
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("NOTIFY_TO")
    if not host or not to:
        return False, "未配置 SMTP_HOST 或 NOTIFY_TO"
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = user or f"radar@{host}"
        msg["To"] = to
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
        return True, f"已发送到 {to}"
    except Exception as e:  # noqa: BLE001
        return False, f"邮件发送失败：{e}"


def send_telegram(text: str) -> tuple[bool, str]:
    """Telegram Bot API 发送。返回 (成功, 说明)。"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID"
    try:
        # Telegram 消息上限 4096 字符，超长截断
        if len(text) > 4000:
            text = text[:4000] + "\n…（已截断，详情见网站）"
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "disable_web_page_preview": True},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return True, "已发送到 Telegram"
        return False, f"Telegram 返回异常：{data}"
    except Exception as e:  # noqa: BLE001
        return False, f"Telegram 发送失败：{e}"


def send_report(subject: str, body: str) -> dict:
    """按配置渠道发送日报。返回各渠道结果。"""
    results: dict[str, tuple[bool, str]] = {}
    if not is_enabled():
        return {"skipped": (True, "通知未启用（NOTIFY_ENABLED=false）")}
    ch = channel()
    if ch in ("email", "both"):
        results["email"] = send_email(subject, body)
    if ch in ("telegram", "both"):
        results["telegram"] = send_telegram(body)
    if not results:
        results["config"] = (False, f"未知渠道：{ch}")
    return results
