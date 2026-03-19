"""
Reddit Collector — AI 相关社区热帖采集
修复点：
1. 补全了被截断的 _parse 函数逻辑。
2. 确保数据解析符合 IntelItem 模型要求。
3. 增加了时区处理和异常防御。
"""

import asyncio
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List
import sys
import os

# 确保可以正确导入 models.py
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

# 预设关注的 AI 社区
SUBREDDITS = ["MachineLearning", "LocalLLaMA", "artificial", "OpenAI"]
REDDIT_JSON = "https://www.reddit.com/r/{sub}/hot.json?limit={n}"

class RedditCollector:
    name = "Reddit"

    def __init__(
        self,
        subreddits: List[str] | None = None,
        min_score: int = 100,
        max_per_sub: int = 15,
    ):
        self.subreddits  = subreddits or SUBREDDITS
        self.min_score   = min_score
        self.max_per_sub = max_per_sub
        # User-Agent 必须唯一，否则会被 Reddit 封禁
        self.user_agent  = f"AI-Intel-Pipeline/1.0 (User={os.getenv('GITHUB_REPOSITORY', 'local')})"

    async def collect(self) -> List[IntelItem]:
        items = []
        for sub in self.subreddits:
            try:
                # 频率控制，防止 429 错误
                await asyncio.sleep(1) 
                batch = await asyncio.to_thread(self._fetch_sub, sub)
                items.extend(batch)
                logger.info(f"Reddit r/{sub}: 采集到 {len(batch)} 条热门讨论")
            except Exception as e:
                logger.warning(f"Reddit r/{sub} 采集失败: {e}")
        return items

    def _fetch_sub(self, subreddit: str) -> List[IntelItem]:
        url = REDDIT_JSON.format(sub=subreddit, n=self.max_per_sub)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.error("Reddit 触发频率限制 (429)")
            raise e

        posts = data.get("data", {}).get("children", [])
        results = []
        for p in posts:
            post_data = p.get("data", {})
            # 过滤掉置顶帖和分数不足的贴
            if post_data.get("stickied"):
                continue
            
            item = self._parse(post_data, subreddit)
            if item.raw.get("score", 0) >= self.min_score:
                results.append(item)
        return results
    def _parse(self, data: dict, subreddit: str) -> IntelItem:
        """解析 Reddit 原始数据为 IntelItem"""
        score = data.get("score", 0)
        title = data.get("title", "No Title")
        permalink = data.get("permalink", "")
        
        # 拼接摘要：正文预览 + 互动数据
        selftext = data.get("selftext", "")
        summary = f"{selftext[:800]}...\n\n👍 Score: {score} | 💬 Comments: {data.get('num_comments')}"

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
