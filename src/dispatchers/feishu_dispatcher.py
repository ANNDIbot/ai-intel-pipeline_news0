"""
Feishu / Lark Dispatcher — sends rich interactive cards via webhook.
Uses the "interactive card" format for beautiful rendering in Feishu.
"""

import json
import logging
import urllib.request
import urllib.error
import asyncio

import sys
sys.path.insert(0, "..")
from models import IntelItem

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_CARD = 8
MAX_CARDS_PER_RUN  = 2


def _score_color(score: float) -> str:
    """Feishu tag colors."""
    if score >= 9:  return "red"
    if score >= 7:  return "orange"
    if score >= 5:  return "yellow"
    return "grey"


def _build_card(items: list[IntelItem]) -> dict:
    """Build a Feishu interactive card payload."""
    elements = []

    for item in items[:MAX_ITEMS_PER_CARD]:
        score_tag = {
            "tag": "text",
            "text": f"评分 {item.score:.1f}",
            "text_size": "normal",
            "text_color": _score_color(item.score),
        }
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**[{item.score:.1f}] {item.title[:100]}**\n"
                    f"{item.key_insight or item.short_summary[:150]}\n"
                    f"来源：{item.source}"
                ),
            },
            "extra": {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看原文"},
                "type": "default",
                "url": item.url,
            },
        })
        elements.append({"tag": "hr"})

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🤖 AI 情报日报",
                },
                "template": "blue",
            },
            "elements": elements,
        },
    }


class FeishuDispatcher:
    name = "Feishu"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def dispatch(self, items: list[IntelItem]):
        if not items:
            return

        # Split into chunks for multiple cards if needed
        chunks = [
            items[i : i + MAX_ITEMS_PER_CARD]
            for i in range(0, min(len(items), MAX_ITEMS_PER_CARD * MAX_CARDS_PER_RUN), MAX_ITEMS_PER_CARD)
        ]

        for chunk in chunks:
            card = _build_card(chunk)
            await asyncio.to_thread(self._send, card)
            await asyncio.sleep(1)

        logger.info("Dispatched %d Feishu card(s) for %d items", len(chunks), len(items))

    def _send(self, payload: dict):
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("code") != 0 and resp.get("StatusCode") != 0:
                    logger.error("Feishu webhook error: %s", resp)
        except urllib.error.HTTPError as e:
            logger.error("Feishu HTTP %d: %s", e.code, e.read())
