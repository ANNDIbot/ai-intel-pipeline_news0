"""
Telegram Dispatcher — pushes scored items to a Telegram channel/group.
Supports MarkdownV2 formatting with score badges and source labels.
"""

import json
import logging
import urllib.request
import urllib.parse
import asyncio
import re
from typing import Optional

import sys
sys.path.insert(0, "..")
from models import IntelItem

logger = logging.getLogger(__name__)

TG_SEND = "https://api.telegram.org/bot{token}/sendMessage"
MAX_ITEMS_PER_RUN = 10   # Safety cap to avoid flooding
MAX_MSG_CHARS = 4000


def _escape_md2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special) + r"])", r"\\\1", text)


def _score_badge(score: float) -> str:
    if score >= 9:   return "🔴"
    if score >= 7:   return "🟠"
    if score >= 5:   return "🟡"
    return "⚪"


def _format_message(items: list[IntelItem]) -> list[str]:
    """Build a list of Telegram messages (split if needed)."""
    header = "🤖 *AI Intelligence Digest*\n\n"
    messages = []
    current = header

    for i, item in enumerate(items[:MAX_ITEMS_PER_RUN], 1):
        badge = _score_badge(item.score)
        title = _escape_md2(item.title[:100])
        insight = _escape_md2(item.key_insight or item.short_summary[:120])
        source = _escape_md2(item.source)
        score_str = f"{item.score:.1f}"
        url = item.url

        block = (
            f"{badge} *\\[{score_str}\\]* {title}\n"
            f"↳ {insight}\n"
            f"📎 [{_escape_md2(source)}]({url})\n\n"
        )

        if len(current) + len(block) > MAX_MSG_CHARS:
            messages.append(current.rstrip())
            current = block
        else:
            current += block

    if current.strip():
        messages.append(current.rstrip())

    return messages


class TelegramDispatcher:
    name = "Telegram"

    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self._url    = TG_SEND.format(token=token)

    async def dispatch(self, items: list[IntelItem]):
        if not items:
            logger.info("No items to dispatch")
            return

        messages = _format_message(items)
        for msg in messages:
            await asyncio.to_thread(self._send, msg)
            await asyncio.sleep(0.5)   # Be gentle with Telegram rate limits

        logger.info("Dispatched %d Telegram message(s) for %d items", len(messages), len(items))

    def _send(self, text: str):
        body = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }).encode()

        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if not resp.get("ok"):
                    logger.error("Telegram API error: %s", resp)
        except urllib.error.HTTPError as e:
            logger.error("Telegram HTTP %d: %s", e.code, e.read())
