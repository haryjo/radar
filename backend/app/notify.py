"""Notifications gratuites via un bot Telegram."""
import html
import logging

import httpx

from . import secrets_store

log = logging.getLogger("radar.notify")


def telegram_enabled() -> bool:
    return bool(secrets_store.get("telegram_bot_token") and secrets_store.get("telegram_chat_id"))


async def send_telegram(text_html: str) -> bool:
    if not telegram_enabled():
        return False
    url = f"https://api.telegram.org/bot{secrets_store.get('telegram_bot_token')}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"chat_id": secrets_store.get("telegram_chat_id"), "text": text_html[:4000],
                                                "parse_mode": "HTML", "disable_web_page_preview": True})
        return resp.status_code == 200
    except httpx.HTTPError as exc:
        log.warning("Telegram indisponible : %s", exc)
        return False


def escape(text: str) -> str:
    return html.escape(text or "", quote=False)
