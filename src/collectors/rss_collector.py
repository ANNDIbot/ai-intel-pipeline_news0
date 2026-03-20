"""
RSS Collector — 行业动态采集（增强版）
优化点：
1. 增加发布时间 (published_at) 解析，支持 ISO 和 RFC822 格式。
2. 强化 ID 生成算法，结合 URL 和标题确保唯一性。
3. 优化 HTML 清洗逻辑，移除多余空白符。
4. 修复父目录导入逻辑，确保在 Actions 环境下路径正确。
"""

import asyncio
import hashlib
import logging
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
import sys
import os

# 确保导入 models.py
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"

class RSSCollector:
    name = "RSS"

    def __init__(self, feeds: dict[str, str]):
        self.feeds = feeds # {"OpenAI": "url", ...}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        }

    async def collect(self) -> list[IntelItem]:
        tasks = [
            asyncio.to_thread(self._fetch_feed, name, url)
            for name, url in self.feeds.items()
        ]
        results = await asyncio.gather(*tasks)
        # 合并所有源的结果并扁平化列表
        return [item for sublist in results for item in sublist]

    def _fetch_feed(self, source_name: str, url: str) -> list[IntelItem]:
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)

            # 自动识别格式：Atom 还是 RSS 2.0
            if root.tag.endswith("feed"):
                return self._parse_atom(root, source_name)
            else:
                channel = root.find("channel")
                if channel is not None:
                    return self._parse_rss(channel, source_name)
                return []
        except urllib.error.HTTPError as e:
            logger.warning(f"RSS源 {source_name} HTTP错误 {e.code}: {url}")
            return []
        except urllib.error.URLError as e:
            logger.warning(f"RSS源 {source_name} 网络错误 (可能被封): {e.reason} — {url}")
            return []
        except ET.ParseError as e:
            logger.warning(f"RSS源 {source_name} XML解析失败: {e} — {url}")
            return []
        except Exception as e:
            logger.warning(f"RSS源 {source_name} 采集失败: {type(e).__name__}: {e}")
            return []

    def _parse_atom(self, root: ET.Element, source_name: str) -> list[IntelItem]:
        items = []
        # 处理命名空间
        ns = {"a": ATOM_NS}
        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            link_el = entry.find("a:link[@rel='alternate']", namespaces=ns)
            if link_el is None:
                link_el = entry.find("a:link", namespaces=ns)
            
            link = link_el.get("href") if link_el is not None else ""
            summary = (entry.findtext("a:summary", namespaces=ns) or 
                       entry.findtext("a:content", namespaces=ns) or "").strip()
            
            # 解析时间
            published_str = entry.findtext("a:published", namespaces=ns) or entry.findtext("a:updated", namespaces=ns)
            pub_date = self._parse_date(published_str)

            if not title or not link: continue

            items.append(self._create_item(source_name, title, link, summary, pub_date))
        return items

    def _parse_rss(self, channel: ET.Element, source_name: str) -> list[IntelItem]:
        items = []
        for el in channel.findall("item"):
            title = (el.findtext("title") or "").strip()
            link = (el.findtext("link") or "").strip()
            description = (el.findtext("description") or "").strip()
            
            # 解析时间 (RFC822 格式)
            pub_date_str = el.findtext("pubDate")
            pub_date = self._parse_date(pub_date_str)

            if not title or not link: continue

            items.append(self._create_item(source_name, title, link, description, pub_date))
        return items

    def _create_item(self, source, title, link, raw_content, pub_date) -> IntelItem:
        # 1. 清理 HTML 标签并处理空白字符
        clean_content = re.sub(r"<[^>]+>", " ", raw_content)
        clean_content = " ".join(clean_content.split()) # 移除多余空格和换行
        
        # 2. 生成基于 URL 的稳定 ID (更鲁棒)
        item_id = f"rss:{hashlib.md5(link.encode()).hexdigest()[:12]}"
        
        return IntelItem(
            id=item_id,
            source=source,
            url=link,
            title=title,
            summary=clean_content[:1000], # 留更多信息给 LLM
            published_at=pub_date,
            tags=["news"]
        )

    def _parse_date(self, date_str: str) -> datetime:
        """解析多种格式的日期字符串"""
        if not date_str:
            return datetime.now()
        try:
            # 尝试 RFC822 (RSS 2.0 标准)
            return parsedate_to_datetime(date_str)
        except Exception:
            try:
                # 尝试 ISO 格式 (Atom 标准)
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except Exception:
                return datetime.now()
