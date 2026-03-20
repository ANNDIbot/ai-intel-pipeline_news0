"""
Dedup Filter — 多维增量去重器
优化点：
1. 双重校验：引入标题归一化去重（Normalized Title），解决不同媒体报道同一新闻的重复问题。
2. 健壮的持久化：增加文件写入前的备份逻辑，防止状态文件损坏。
3. 灵活的 TTL：从 7 天延长至 14 天（默认），更适合周刊级或长跨度情报追踪。
4. 性能优化：使用 set 记录本次运行的增量，减少循环中的 IO 压力。
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
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

class DedupFilter:
    def __init__(self, state_file: Path = Path("state/last_seen.json"), ttl_days: int = 14):
        self.state_file = state_file
        self.ttl_days = ttl_days
        self.seen_ids: dict[str, str] = {}    # id -> timestamp
        self.seen_titles: dict[str, str] = {} # normalized_title -> timestamp
        self._load_state()

    def _normalize_title(self, title: str) -> str:
        """归一化标题：移除空格、特殊符号、统一大小写，用于识别相似标题"""
        if not title:
            return ""
        # 移除所有非中文字符、字母和数字
        res = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", title)
        return res.lower()

    def _load_state(self):
        """从磁盘恢复去重状态"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 兼容旧版本格式
                if isinstance(data, dict):
                    self.seen_ids = data.get("ids", data) # 如果是旧格式，直接赋值给 ids
                    self.seen_titles = data.get("titles", {})
                logger.info(f"Dedup: 已加载 {len(self.seen_ids)} 条历史 ID")
        except Exception as e:
            logger.warning(f"无法读取状态文件 ({e})，将重新开始采集")
            self.seen_ids = {}
            self.seen_titles = {}

    def filter(self, items: List[IntelItem]) -> List[IntelItem]:
        """核心过滤逻辑：ID 命中或标题命中均视为重复"""
        fresh = []
        # 用本地集合跟踪本次 run 内的新条目，防止同批次重复（历史状态不含本次）
        session_ids: set = set()
        session_titles: set = set()

        for item in items:
            norm_title = self._normalize_title(item.title)

            # 1. 检查历史 ID
            if item.id in self.seen_ids:
                continue
            # 2. 检查本次 run 内 ID 重复
            if item.id in session_ids:
                continue
            # 3. 检查历史标题
            if norm_title and norm_title in self.seen_titles:
                logger.debug(f"Title Dedup (历史): 拦截相似内容 -> {item.title[:30]}...")
                continue
            # 4. 检查本次 run 内标题重复（原始代码 bug：这一步缺失）
            if norm_title and norm_title in session_titles:
                logger.debug(f"Title Dedup (本次): 拦截相似内容 -> {item.title[:30]}...")
                continue

            fresh.append(item)
            session_ids.add(item.id)
            if norm_title:
                session_titles.add(norm_title)

        logger.info(f"去重结果: 原始 {len(items)} 条 -> 过滤后 {len(fresh)} 条")
        return fresh

    def save_state(self, items: List[IntelItem]):
        """持久化存储，并执行过期清理 (TTL)"""
        now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(days=self.ttl_days)).isoformat()
        now_str = now_dt.isoformat()

        # 1. 更新本次抓取的数据
        for item in items:
            self.seen_ids[item.id] = now_str
            norm_title = self._normalize_title(item.title)
            if norm_title:
                self.seen_titles[norm_title] = now_str

        # 2. 清理过期数据 (TTL)
        self.seen_ids = {k: v for k, v in self.seen_ids.items() if v >= cutoff}
        self.seen_titles = {k: v for k, v in self.seen_titles.items() if v >= cutoff}

        # 3. 安全写入（先写临时文件再重命名，防止崩溃导致文件损坏）
        tmp_file = self.state_file.with_suffix(".tmp")
        try:
            state_data = {
                "ids": self.seen_ids,
                "titles": self.seen_titles,
                "updated_at": now_str
            }
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"保存状态文件失败: {e}")
