"""
GitHub Trending Collector — 高价值 AI 仓库采集
优化点：
1. API 侧过滤：将 min_stars 直接写入查询语句，提高单次请求的有效数据量。
2. 动态排序：增加 sort='stars' 参数，确保优先获取最热门的项目。
3. 健壮的 Token 处理：统一通过 headers 处理认证，增加对速率限制的预警。
4. 摘要增强：自动解析 README 摘要并附带仓库的 Topic 标签。
"""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Any
import sys

# 路径兼容处理
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

GH_SEARCH = "https://api.github.com/search/repositories"
# 预设的 AI 核心关键词
AI_TOPICS = ["llm", "agent", "rag", "transformer", "diffusion", "vlm"]

class GitHubCollector:
    name = "GitHub"

    def __init__(self, languages: list[str], topics: list[str], min_stars: int = 50):
        self.languages = languages
        self.topics    = list(set(topics + AI_TOPICS)) # 合并并去重
        self.min_stars = min_stars

    async def collect(self) -> list[IntelItem]:
        items = []
        # GitHub 搜索 API 对并发比较敏感，建议串行处理不同语言以保护 IP
        for lang in self.languages:
            try:
                batch = await asyncio.to_thread(self._search, lang)
                items.extend(batch)
                logger.info(f"GitHub [{lang}]: 发现 {len(batch)} 个潜在高价值项目")
                # 稍微延迟，保护 API 频率
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"GitHub {lang} 采集异常: {e}")
        
        return self._deduplicate(items)

    def _search(self, language: str) -> list[IntelItem]:
        # 问题根因：topic: 标签是仓库作者手动打的，大量 AI 仓库没有打标签
        # 改为在名称+描述中搜索关键词（in:name,description），命中率大幅提升
        last_week = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        # 高频 AI 关键词，出现在名称或描述里即命中
        keywords = ["llm", "agent", "rag", "gpt", "claude", "gemini", "deepseek",
                    "transformer", "diffusion", "multimodal", "embedding", "finetune"]
        kw_q = " OR ".join(keywords)

        query_str = (
            f"({kw_q}) in:name,description"
            f" language:{language}"
            f" stars:>={self.min_stars}"
            f" pushed:>{last_week}"
        )

        params = {
            "q": query_str,
            "sort": "stars",
            "order": "desc",
            "per_page": 30
        }
        
        encoded_params = urllib.parse.urlencode(params)
        url = f"{GH_SEARCH}?{encoded_params}"
        
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AI-Intel-Pipeline/1.0"
        }
        
        # 💡 Token 注入逻辑
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            logger.warning("未检测到 GITHUB_TOKEN，采集频率将受到严格限制。")

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
                
            repos = data.get("items", [])
            return [self._parse(repo, language) for repo in repos]
        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.error("GitHub API 拒绝访问：可能触发了速率限制。")
            raise e

    def _parse(self, repo: dict, language: str) -> IntelItem:
        stars   = repo.get("stargazers_count", 0)
        forks   = repo.get("forks_count", 0)
        topics  = repo.get("topics", [])
        desc    = repo.get("description") or "No description provided."
        
        # 构造丰富摘要供 LLM 评分
        summary = (
            f"Description: {desc}\n"
            f"Stats: ⭐ {stars:,} | 🍴 {forks:,}\n"
            f"Topics: {', '.join(topics[:8])}"
        )
        
        return IntelItem(
            id=f"gh:{repo['id']}",
            source="GitHub",
            url=repo["html_url"],
            title=repo["full_name"],
            summary=summary,
            tags=["github", language.lower()] + topics[:3],
            raw={"stars": stars, "forks": forks, "last_push": repo.get("pushed_at")}
        )

    def _deduplicate(self, items: list[IntelItem]) -> list[IntelItem]:
        """按仓库 ID 去重"""
        seen = set()
        unique = []
        for item in items:
            if item.id not in seen:
                unique.append(item)
                seen.add(item.id)
        return unique
