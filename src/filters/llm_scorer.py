"""
LLM Scorer — 行业深度分析评分器
优化点：
1. 强化 Prompt 逻辑：引入量化评分标准，确保 8.5 分的高门槛具有一致性。
2. 指数退避重试：针对 API 抖动或并发超限自动重试，确保任务完成率。
3. 智能截断：针对长文本（如 Jina 抓取结果）进行预处理，保护 Token 窗口。
4. 容错 JSON 解析：增强了对 LLM 偶尔输出非规范 JSON 的修复能力。
"""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
import time
from typing import Optional, List
import sys

# 路径兼容
try:
    from models import IntelItem
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import IntelItem

logger = logging.getLogger(__name__)

# ── 评分标准定义 ──────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位世界级的 AI 科技分析师。请评估以下资讯的【商业与技术价值】。
评分标准（1-10）：
- 9.0-10: 革命性突破（如 Transformer 发布、Sora 发布、重大基座模型更新）。
- 8.0-8.9: 高价值（重要技术报告、主流工具重大更新、大厂核心动向、高引用论文）。
- 6.0-7.9: 一般价值（常规产品迭代、普通行业新闻、偏应用层的工具）。
- 1.0-5.9: 低价值（营销软文、无实质内容的讨论、旧闻重发）。

你的输出必须是严格的 JSON 格式，包含：
{
  "score": 浮点数,
  "reasoning": "一句话理由，说明为何给这个分",
  "key_insight": "一句话中文总结，指出最核心的干货",
  "tags": ["标签1", "标签2"]
}
注意：无论原文是什么语言，reasoning 和 key_insight 必须使用简洁的中文。"""

class LLMScorer:
    def __init__(self, score_threshold: float = 8.5, provider: str = "deepseek", concurrency: int = 5):
        self.score_threshold = score_threshold
        self.concurrency = concurrency
        
        # 配置加载
        config = {
            "deepseek": {
                "url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-chat",
                "key": os.getenv("DEEPSEEK_API_KEY")
            }
        }
        self.active_cfg = config.get(provider)
        if not self.active_cfg or not self.active_cfg["key"]:
            raise ValueError(f"未配置有效的 LLM Provider 或缺少 API KEY")

    async def score_batch(self, items: List[IntelItem]) -> List[IntelItem]:
        sem = asyncio.Semaphore(self.concurrency)
        tasks = [self._score_single_with_retry(item, sem) for item in items]
        return await asyncio.gather(*tasks)

    async def _score_single_with_retry(self, item: IntelItem, sem: asyncio.Semaphore, retries: int = 3) -> IntelItem:
        async with sem:
            for attempt in range(retries):
                try:
                    # 预处理：防止 summary 过长
                    content = item.summary[:3000] if item.summary else "无内容"
                    
                    user_msg = f"Source: {item.source}\nTitle: {item.title}\nContent: {content}"
                    
                    # 异步调用 API
                    resp_json = await asyncio.to_thread(self._call_api, user_msg)
                    
                    # 填充数据
                    item.score = float(resp_json.get("score", 0))
                    item.reasoning = resp_json.get("reasoning", "")
                    item.key_insight = resp_json.get("key_insight", "")
                    
                    # 标签合并与去重
                    new_tags = resp_json.get("tags", [])
                    item.tags = list(set(item.tags + new_tags))
                    
                    return item
                except Exception as e:
                    if attempt < retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(f"评分失败，{wait_time}s 后重试: {item.title[:20]}... Error: {e}")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"评分最终失败: {item.title} | {e}")
                    return item

    def _call_api(self, user_msg: str) -> dict:
        body = json.dumps({
            "model": self.active_cfg["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.1, # 降低随机性，确保 JSON 稳定
            "response_format": {"type": "json_object"} # 如果模型支持 JSON Mode
        }).encode()

        req = urllib.request.Request(
            self.active_cfg["url"],
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.active_cfg['key']}"
            }
        )

        with urllib.request.urlopen(req, timeout=45) as r:
            raw_resp = json.loads(r.read())
            content = raw_resp["choices"][0]["message"]["content"]
            return self._parse_json_robustly(content)

    def _parse_json_robustly(self, text: str) -> dict:
        """鲁棒的 JSON 提取逻辑"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试截取 Markdown 代码块中的 JSON
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
            raise ValueError("无法解析 LLM 返回的 JSON 内容")
