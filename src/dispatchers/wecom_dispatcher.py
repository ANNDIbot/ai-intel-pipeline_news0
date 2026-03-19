"""
WeCom Dispatcher — 企业微信高价值情报分发
优化点：
1. 字节流控：自动计算 Markdown 长度，防止超过 4096 字节限制（改为分两条发送）。
2. UI 视觉强化：优化了引用块（Quote）的显示逻辑，增强阅读节奏感。
3. 鲁棒性：增加了简单的网络重试逻辑，确保推送成功率。
4. 字段对齐：与最新的 models.py 字段完全对齐。
"""

import json
import logging
import urllib.request
import asyncio
import time
from typing import List
import sys
import os

# 路径兼容
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

def _get_number_emoji(index: int) -> str:
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    return emojis[index] if index < len(emojis) else "🔹"

class WeComDispatcher:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.max_bytes = 4000  # 企业微信限制约 4096 字节，保留余量

    async def dispatch(self, items: List[IntelItem]):
        if not items:
            return

        # 1. 按照高分排序，确保最有价值的在前面
        items.sort(key=lambda x: x.score, reverse=True)
        
        # 2. 构造消息块（解决长消息截断问题）
        chunks = self._build_message_chunks(items)
        
        # 3. 执行推送
        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(1) # 频率限制保护
            await asyncio.to_thread(self._send_with_retry, chunk)

    def _build_message_chunks(self, items: List[IntelItem]) -> List[str]:
        """将资讯列表构建为多个符合长度限制的 Markdown 块"""
        chunks = []
        current_header = f"## 🤖 AI 行业情报简报 ({len(items)} 条)\n"
        current_chunk = current_header
        
        for i, item in enumerate(items):
            num_icon = _get_number_emoji(i)
            score = getattr(item, 'score', 0.0)
            # 核心总结：优先使用 LLM 生成的 key_insight
            insight = getattr(item, 'key_insight', None) or getattr(item, 'summary', '暂无内容')
            if len(insight) > 300:
                insight = insight[:297] + "..."

            # 组装单条资讯的 Markdown
            block = (
                f"{num_icon} **[{score:.1f}] {item.title}**\n"
                f"> 💡 **核心：** {insight}\n"
                f"🔗 [查看原文]({item.url}) | 来源：{item.source}\n"
                f"\n---\n"
            )
            
            # 如果加上这一块超长了，就开启新块
            if len((current_chunk + block).encode('utf-8')) > self.max_bytes:
                chunks.append(current_chunk)
                current_chunk = current_header + block
            else:
                current_chunk += block
        
        chunks.append(current_chunk)
        return chunks

    def _send_with_retry(self, content: str, retries: int = 3):
        """执行 Webhook 发送，带指数退避重试"""
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    self.webhook_url,
                    data=body,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    res = json.loads(r.read())
                    if res.get("errcode") == 0:
                        return
                    else:
                        logger.warning(f"WeCom 接口返回错误: {res}")
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                logger.error(f"WeCom 推送最终失败 ({self.webhook_url}): {e}")
