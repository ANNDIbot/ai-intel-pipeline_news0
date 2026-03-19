"""
Reddit Collector — AI 相关社区热帖采集
修复点：
1. 补全了被截断的 _parse 函数逻辑。
2. 确保数据解析符合 IntelItem 模型要求。
"""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List

import sys
# 确保可以正确导入 models.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from models import IntelItem
except ImportError:
    # 备用方案，处理不同环境下的导入
    from src.models import IntelItem

logger = logging.getLogger(__name__)

REDDIT_JSON = "https://www.reddit.com/r/{sub}/hot.json?limit={n}"

class RedditCollector:
    name = "Reddit"

    def __init__(
        self,
        subreddits: List[str] | None = None,
        min_score: int = 100,
        max_per_sub: int = 15,
    ):
        # 优先使用 config.yml 传入的 subreddits
        self.subreddits  = subreddits or ["MachineLearning", "LocalLLaMA", "artificial", "OpenAI"]
        self.min_score   = min_score
        self.max_per_sub = max_per_sub
        self.user_agent  = f"AI-Intel-Pipeline/1.0 (User={os.getenv('GITHUB_REPOSITORY', 'local')})"

    async def collect(self) -> List[IntelItem]:
        items = []
        for sub in self.subreddits:
            try:
                await asyncio.sleep(1) # 频率控制，防止 429
                batch = await asyncio.to_thread(self._fetch_sub, sub)
                items.extend(batch)
            except Exception as e:
                logger.warning(f"Reddit r/{sub} 失败: {e}")
        return items

    def _fetch_sub(self, subreddit: str) -> List[IntelItem]:
        url = REDDIT_JSON.format(sub=subreddit, n=self.max_per_sub)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        posts = data.get("data", {}).get("children", [])
        results = []
        for p in posts:
            item = self._parse(p.get("data", {}), subreddit)
            # 仅保留达到分数门槛的帖子
            if item and item.raw.get("score", 0) >= self.min_score:
                results.append(item)
        return results

    def _parse(self, data: dict, subreddit: str) -> IntelItem:
        """解析 Reddit 原始数据为 IntelItem"""
        score = data.get("score", 0)
        title = data.get("title", "No Title")
        permalink = data.get("permalink", "")
        
        # 拼接摘要：正文前部 + 互动数据
        selftext = data.get("selftext", "")
        summary = f"{selftext[:1000]}\n\n👍 Score: {score} | 💬 Comments: {data.get('num_comments')}"

        return IntelItem(
            id=f"reddit:{data.get('id')}",
            source=f"Reddit/r/{subreddit}",
            url=f"https://www.reddit.com{permalink}",
            title=title,
            summary=summary,
            published_at=datetime.fromtimestamp(data.get("created_utc", 0), tz=timezone.utc),
            tags=["reddit", subreddit.lower()],
            raw={"score": score, "num_comments": data.get("num_comments")}
        )
