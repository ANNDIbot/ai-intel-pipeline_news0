"""
AI Intel Pipeline - 共享数据模型
定义了全流程通用的数据结构 IntelItem。
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Any, Dict, List


@dataclass
class IntelItem:
    """代表从任何来源获取的单条情报。"""

    # 身份标识
    id: str                        # 唯一标识 (如 arxiv:2406.XXXXX, github:owner/repo)
    source: str                    # 来源名称 (如 "OpenAI", "HackerNews")
    url: str                       # 原始链接

    # 内容核心
    title: str
    summary: str                   # 摘要或简介
    authors: List[str] = field(default_factory=list)
    published_at: Optional[datetime] = None

    # LLM 增强字段 (由 LLMScorer 填充)
    score: float = 0.0             # 1-10 分
    reasoning: str = ""            # LLM 给出的评分理由
    key_insight: str = ""          # 一句话核心洞察

    # 扩展信息
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict) # 清洗后的特定元数据 (如 stars, category)
    raw: Dict[str, Any] = field(default_factory=dict)      # 原始 API 响应

    def __post_init__(self):
        """初始化后的清理逻辑。"""
        # 确保 summary 是字符串，防止某些 API 返回 None
        if self.summary is None:
            self.summary = ""
        # 限制摘要长度，防止内存占用过大
        self.summary = self.summary.strip()

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if not isinstance(other, IntelItem):
            return False
        return self.id == other.id

    @property
    def short_summary(self) -> str:
        """用于消息推送的截断摘要。"""
        return self.summary[:280] + ("..." if len(self.summary) > 280 else "")

    def to_dict(self) -> Dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        # datetime 对象无法直接序列化，需转为 ISO 字符串
        if self.published_at:
            data['published_at'] = self.published_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntelItem':
        """从字典还原对象 (用于从 last_seen.json 加载状态)。"""
        if data.get('published_at'):
            try:
                data['published_at'] = datetime.fromisoformat(data['published_at'])
            except (ValueError, TypeError):
                data['published_at'] = None
        return cls(**data)
