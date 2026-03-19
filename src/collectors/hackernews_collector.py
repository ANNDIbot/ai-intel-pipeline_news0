"""
Hacker News Collector — 顶级社区热点采集
优化点：
1. 增加请求重试逻辑：应对 HN API 偶尔的连接重置问题。
2. 提取正文内容：对于 Ask HN 或讨论类帖子，抓取 text 字段供 LLM 评分。
3. 时间戳转换：将 HN 的 Unix 时间戳转为标准的 datetime 对象。
4. 增强并发安全性：维持 Semaphore 限制，防止被 Firebase 后端封禁。
"""

import asyncio
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, Any
import sys
import os

# 确保导入路径正确
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

HN_TOP    = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM   = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
BATCH_SIZE = 150   # 检查前 150 条热帖

class HackerNewsCollector:
    name = "HackerNews"

    def __init__(self, keywords: list[str], min_score: int = 50):
        self.keywords = [k.lower() for k in keywords]
        self.min_score = min_score
        self.headers = {
            "User-Agent": "AI-Intel-Pipeline/1.0 (HackerNews Collector)"
        }

    async def collect(self) -> list[IntelItem]:
        try:
            # 1. 获取最热门帖子 ID 列表
            top_ids = await asyncio.to_thread(self._fetch_json, HN_TOP)
            if not top_ids:
                return []
            
            target_ids = top_ids[:BATCH_SIZE]
            
            # 2. 并发获取详细内容 (限制并发数为 15，HN API 比较敏感)
            sem = asyncio.Semaphore(15)
            tasks = [self._fetch_and_parse(sid, sem) for sid in target_ids]
            
            results = await asyncio.gather(*tasks)
            # 过滤无效结果
            return [r for r in results if r is not None]
            
        except Exception as e:
            logger.error(f"HackerNews 全局采集异常: {e}")
            return []

    async def _fetch_and_parse(self, story_id: int, sem: asyncio.Semaphore) -> Optional[IntelItem]:
        async with sem:
            try:
                url = HN_ITEM.format(id=story_id)
                data = await asyncio.to_thread(self._fetch_json, url)
                return self._parse(data)
            except Exception:
                return None

    def _fetch_json(self, url: str, retries: int = 2) -> Any:
        """带重试机制的 JSON 获取逻辑"""
        for i in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except (urllib.error.URLError, ConnectionResetError) as e:
                if i < retries:
                    time_to_sleep = (i + 1) * 2
                    continue
                logger.warning(f"无法访问 HN API ({url}): {e}")
                break
        return None

    def _parse(self, data: dict) -> Optional[IntelItem]:
        if not data or data.get("type") != "story" or data.get("dead") or data.get("deleted"):
            return None

        title = (data.get("title") or "").strip()
        score = data.get("score", 0)
        # 如果帖子没有外部 URL，则指向 HN 讨论页本身
        item_url = data.get("url") or f"https://news.ycombinator.com/item?id={data['id']}"
        
        # 关键词与分数过滤
        if score < self.min_score:
            return None
            
        title_lower = title.lower()
        if not any(kw in title_lower for kw in self.keywords):
            return None

        # 提取发布时间
        pub_date = None
        if "time" in data:
            pub_date = datetime.fromtimestamp(data["time"])

        # 构建摘要：结合分数、评论数以及可能的正文 (text 字段)
        comments_count = data.get("descendants", 0)
        summary_parts = [f"HN Score: {score} | Comments: {comments_count}"]
        
        # 如果是 Ask HN 或有正文的帖子
        if "text" in data:
            # 简单去除 HTML 标签
            import re
            text = re.sub(r"<[^>]+>", " ", data["text"])
            summary_parts.append(text[:500])
        
        return IntelItem(
            id=f"hn:{data['id']}",
            source="HackerNews",
            url=item_url,
            title=title,
            summary=" \n".join(summary_parts),
            published_at=pub_date,
            tags=["hackernews", "trending"],
            raw={"score": score, "comments": comments_count}
        )
