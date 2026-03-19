"""
Reddit Collector — AI 相关社区热帖采集
优化点：
1. 强化 User-Agent 标识，降低被 Reddit 429 封禁的概率。
2. 增加内容抓取深度：将正文截取提升至 2000 字符，确保 LLM 有足够上下文。
3. 增加频率控制：在不同 Subreddit 采集之间引入强制延迟。
4. 修复父目录导入路径问题。
"""

import asyncio
import json
import logging
import time
import urllib.request
import urllib.error
from typing import Optional
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
SUBREDDITS  = ["MachineLearning", "LocalLLaMA", "artificial", "OpenAI"]
REDDIT_JSON = "https://www.reddit.com/r/{sub}/hot.json?limit={n}&t=day"

class RedditCollector:
    name = "Reddit"

    def __init__(
        self,
        subreddits: list[str] | None = None,
        min_score: int = 100,
        max_per_sub: int = 15,
    ):
        self.subreddits  = subreddits or SUBREDDITS
        self.min_score   = min_score
        self.max_per_sub = max_per_sub
        # 💡 重要：Reddit 要求 User-Agent 必须包含唯一的 App ID 或开发者信息
        self.user_agent  = f"AI-Intel-Pipeline/1.0 (Language=Python; Origin=GitHubActions; User={os.getenv('GITHUB_REPOSITORY', 'local')})"

    async def collect(self) -> list[IntelItem]:
        items = []
        for sub in self.subreddits:
            try:
                # 💡 频率控制：每抓一个 Subreddit 休息 1 秒，防止触发 429
                await asyncio.sleep(1)
                
                batch = await asyncio.to_thread(self._fetch_sub, sub)
                items.extend(batch)
                logger.info(f"Reddit r/{sub}: 成功采集 {len(batch)} 条热门讨论")
            except Exception as e:
                logger.warning(f"Reddit r/{sub} 采集失败: {e}")
                
        return items

    def _fetch_sub(self, subreddit: str) -> list[IntelItem]:
        url = REDDIT_JSON.format(sub=subreddit, n=self.max_per_sub)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", self.user_agent)
        
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.error(f"Reddit 触发速率限制 (429)，建议降低采集频率。")
            raise e

        posts = data.get("data", {}).get("children", [])
        results = []
        for post in posts:
            item = self._parse(post.get("data", {}), subreddit)
            if item:
                results.append(item)
        return results

    def _parse(self,
