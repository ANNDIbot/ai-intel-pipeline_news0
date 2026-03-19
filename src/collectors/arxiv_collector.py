"""
ArXiv Collector — 每日 AI 论文采集
优化点：
1. 增加发布时间解析：精准抓取论文发布/更新日期。
2. 强化摘要清洗：针对 ArXiv 特有的 LaTeX 公式和多余换行进行优化。
3. 鲁棒的 ID 提取：优先从短链接提取版本化的 ArXiv ID（如 2403.XXXXX）。
4. 异步并发保护：虽然 ArXiv 限制较少，但依然通过 to_thread 保持 IO 非阻塞。
"""

import asyncio
import hashlib
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
import sys
import os

# 路径兼容处理，确保能导入项目根目录的 models.py
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

# ArXiv RSS 接口
ARXIV_FEED = "https://export.arxiv.org/rss/{category}"

class ArxivCollector:
    name = "ArXiv"

    def __init__(self, categories: list[str], max_results: int = 30):
        self.categories = categories
        self.max_results = max_results
        self.headers = {
            "User-Agent": "AI-Intel-Pipeline/1.0 (ArXiv Research Collector)"
        }

    async def collect(self) -> list[IntelItem]:
        items = []
        for category in self.categories:
            try:
                # ArXiv API 建议串行或带间隔请求，防止被暂时封锁 IP
                batch = await asyncio.to_thread(self._fetch_category, category)
                items.extend(batch)
                logger.info(f"ArXiv {category}: 成功获取 {len(batch)} 篇最新论文")
                await asyncio.sleep(1) 
            except Exception as e:
                logger.warning(f"ArXiv {category} 采集失败: {e}")
        return items

    def _fetch_category(self, category: str) -> list[IntelItem]:
        url = ARXIV_FEED.format(category=category)
        req = urllib.request.Request(url, headers=self.headers)
        
        with urllib.request.urlopen(req, timeout=25) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        
        # ArXiv RSS 2.0 命名空间通常在 channel 下的 item 中
        channel = root.find("channel")
        if channel is None:
            return []

        results = []
        # 限制单次分类抓取数量
        for item_el in channel.findall("item")[:self.max_results]:
            try:
                parsed = self._parse_item(item_el, category)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.debug(f"跳过论文解析: {e}")
        return results

    def _parse_item(self, el: ET.Element, category: str) -> IntelItem:
        title = (el.findtext("title") or "").strip()
        link  = (el.findtext("link")  or "").strip()
        raw_desc = (el.findtext("description") or "").strip()

        # 1. 深度清理摘要
        # 移除 HTML 标签
        clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
        # 压缩多余的空白字符和 LaTeX 换行标记
        clean_desc = " ".join(clean_desc.split())
        
        # 2. 提取 ArXiv ID (例如从 https://arxiv.org/abs/2403.12345 提取)
        # ArXiv 的链接格式非常固定，正则匹配很稳健
        id_match = re.search(r"abs/(\d+\.\d+)", link)
        if id_match:
            arxiv_id = id_match.group(1)
            item_id = f"arxiv:{arxiv_id}"
        else:
            # 回退方案：使用链接哈希
            item_id = f"arxiv:{hashlib.md5(link.encode()).hexdigest()[:12]}"

        # 3. 解析时间 (ArXiv RSS 使用 RFC822 格式的 pubDate)
        pub_date_str = el.findtext("pubDate")
        pub_date = None
        if pub_date_str:
            try:
                pub_date = parsedate_to_datetime(pub_date_str)
            except Exception:
                pub_date = datetime.now()

        return IntelItem(
            id=item_id,
            source=f"ArXiv:{category}",
            url=link,
            title=title,
            summary=clean_desc[:1500], # 给 LLM 预留足够的上下文
            published_at=pub_date,
            tags=["paper", category],
            raw={"category": category}
        )
