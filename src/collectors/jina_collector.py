import asyncio
import hashlib
import logging
import urllib.request
import sys
import os
import re
from models import IntelItem

logger = logging.getLogger(__name__)

class JinaCollector:
    name = "JinaReader"

    def __init__(self, urls: dict[str, str]):
        self.urls = urls  # 格式: {"36氪": "https://36kr.com/newsflashes", ...}
        self.base_api = "https://r.jina.ai/"

    async def collect(self) -> list[IntelItem]:
        # 使用 asyncio.gather 并发执行抓取任务
        tasks = [
            asyncio.to_thread(self._fetch_url, name, url)
            for name, url in self.urls.items()
        ]
        results = await asyncio.gather(*tasks)
        
        # 过滤掉抓取失败的 None 结果
        return [r for r in results if r]

    def _fetch_url(self, name: str, url: str) -> IntelItem:
        """同步抓取逻辑，由 to_thread 异步调用"""
        try:
            full_url = f"{self.base_api}{url}"
            req = urllib.request.Request(full_url)
            
            # 💡 优先从环境变量读取 JINA_API_KEY 以提高成功率和速率限制
            jina_key = os.getenv("JINA_API_KEY")
            if jina_key:
                req.add_header("Authorization", f"Bearer {jina_key}")
            
            # 模拟浏览器以减少被拦截风险
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode("utf-8")
            
            # 💡 逻辑优化：从 Jina 返回的 Markdown 中提取第一个一级标题作为真实标题
            # Jina 通常会将原网页标题放在 Markdown 最顶部的 # 后面
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            extracted_title = title_match.group(1).strip() if title_match else f"{name} 最新动态"
            
            # 生成基于 URL 的唯一 ID
            item_id = f"jina:{hashlib.md5((name + url).encode()).hexdigest()[:12]}"
            
            # 清理内容：Jina 返回内容可能过长，截取前 4000 字符交给 LLM 处理
            return IntelItem(
                id=item_id,
                source=name,
                url=url,
                title=extracted_title,
                summary=content[:4000], # 提供更丰富的上下文给 LLMScorer
                tags=["web_scan", name]
            )
        except Exception as e:
            logger.warning(f"JinaCollector 抓取 {name} ({url}) 失败: {e}")
            return None
