"""
Alert output formatting and notification dispatch.

Supports: Console, Telegram, Slack, Email.
Configure via environment variables (see .env.example).
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import sqlite3
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from pathlib import Path

import requests

from src.config import SQLITE_DB_PATH, TICKER_DISPLAY
from src.signals import Alert

logger = logging.getLogger(__name__)

HKT = timezone(timedelta(hours=8))

LEVEL_EMOJI = {
    "INFO": "\U0001f4ca",       # 📊
    "WATCH": "\u26a0\ufe0f",    # ⚠️
    "ALERT": "\U0001f534",       # 🔴
    "TRADE_SIGNAL": "\U0001f7e2", # 🟢 (buy) or 🔴 (sell) — handled in formatter
}


def format_alert_json(alert: Alert) -> dict:
    """Build the structured JSON payload per spec."""
    now = datetime.now(HKT)
    payload = {
        "timestamp": now.isoformat(),
        "ticker": TICKER_DISPLAY,
        "signal_id": alert.signal_id,
        "signal_name": alert.signal_name,
        "level": alert.level,
        "message": alert.message,
        "context": alert.context,
    }
    if alert.suggested_action:
        payload["suggested_action"] = alert.suggested_action
    return payload


def format_alert_text(alert: Alert) -> str:
    """Human-readable single-line format for console / messaging."""
    emoji = LEVEL_EMOJI.get(alert.level, "")
    if alert.level == "TRADE_SIGNAL":
        emoji = "\U0001f534" if "SELL" in alert.signal_id else "\U0001f7e2"
    parts = [f"{emoji} [{alert.level}] {alert.message}"]
    if alert.suggested_action:
        parts.append(f"  -> {alert.suggested_action}")
    return "\n".join(parts)


# ──────────────────────────────────────────────
#  Dispatch
# ──────────────────────────────────────────────

def dispatch_alerts(alerts: list[Alert], composite_ids: list[str] | None = None) -> None:
    """Send alerts through all configured channels."""
    if not alerts:
        logger.info("No alerts to dispatch.")
        return

    # Attach composite_signals_active to each alert's JSON
    for a in alerts:
        a.context["composite_signals_active"] = composite_ids or []

    # Always print to console
    _print_console(alerts)

    # Persist to SQLite
    _save_to_db(alerts)

    # Optional channels
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        _send_telegram(alerts)

    if os.environ.get("SLACK_WEBHOOK_URL"):
        _send_slack(alerts)

    if os.environ.get("SMTP_HOST"):
        _send_email(alerts)


def _print_console(alerts: list[Alert]) -> None:
    print("\n" + "=" * 60)
    print(f"  {TICKER_DISPLAY} Signal Monitor — {datetime.now(HKT).strftime('%Y-%m-%d %H:%M HKT')}")
    print("=" * 60)
    for a in alerts:
        print(format_alert_text(a))
    print("=" * 60 + "\n")


def _save_to_db(alerts: list[Alert]) -> None:
    """Persist alerts to local SQLite for history."""
    db_path = Path(SQLITE_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            signal_id TEXT NOT NULL,
            signal_name TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            context_json TEXT,
            suggested_action TEXT
        )
    """)
    now = datetime.now(HKT).isoformat()
    for a in alerts:
        conn.execute(
            "INSERT INTO alerts (timestamp, signal_id, signal_name, level, message, context_json, suggested_action) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, a.signal_id, a.signal_name, a.level, a.message,
             json.dumps(a.context, ensure_ascii=False), a.suggested_action),
        )
    conn.commit()
    conn.close()
    logger.info("Saved %d alerts to %s", len(alerts), db_path)


def _send_telegram(alerts: list[Alert]) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    text = "\n\n".join(format_alert_text(a) for a in alerts)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram notification sent.")
    except Exception as e:
        logger.error("Telegram send failed: %s", e)


def _send_slack(alerts: list[Alert]) -> None:
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    text = "\n\n".join(format_alert_text(a) for a in alerts)
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        logger.info("Slack notification sent.")
    except Exception as e:
        logger.error("Slack send failed: %s", e)


def _send_email(alerts: list[Alert]) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to_addr = os.environ["SMTP_TO"]

    body = "\n\n".join(format_alert_text(a) for a in alerts)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[{TICKER_DISPLAY}] Signal Alert — {datetime.now(HKT).strftime('%Y-%m-%d')}"
    msg["From"] = user
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        logger.info("Email notification sent.")
    except Exception as e:
        logger.error("Email send failed: %s", e)
