"""
AI Intelligence Pipeline - 核心调度器 (V2 加固版)
功能：
1. 协调多源采集（RSS, Jina, Arxiv, GitHub, HN, Reddit）。
2. 调用多维去重过滤（ID + 标题归一化）。
3. 执行 LLM 深度评分与总结（带并发控制与重试）。
4. 实现企业微信自动化分发（带字节流控与分块）。
"""

import asyncio
import logging
import sys
import os
import yaml
from pathlib import Path

# 导入自定义组件
from collectors.arxiv_collector import ArxivCollector
from collectors.rss_collector import RSSCollector
from collectors.hackernews_collector import HackerNewsCollector
from collectors.github_collector import GitHubCollector
from collectors.jina_collector import JinaCollector
from collectors.reddit_collector import RedditCollector

from filters.dedup_filter import DedupFilter
from filters.llm_scorer import LLMScorer
from dispatchers.wecom_dispatcher import WeComDispatcher

# ── 日志配置 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("state/pipeline.log", encoding="utf-8")
    ],
)
logger = logging.getLogger("pipeline")

def load_config():
    """从多路径兼容加载 config/config.yml"""
    possible_paths = [
        Path("config/config.yml"),
        Path("../config/config.yml"),
        Path(os.path.dirname(__file__)) / "../config/config.yml"
    ]
    for path in possible_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    logger.error("❌ 无法找到配置文件 config.yml，请检查路径。")
    sys.exit(1)

async def run_pipeline():
    # 0. 初始化配置
    config = load_config()
    pipe_cfg = config.get("pipeline", {})
    coll_cfg = config.get("collectors", {})
    
    # 实例化去重过滤器 (TTL 同步配置)
    deduper = DedupFilter(
        state_file=Path("state/last_seen.json"),
        ttl_days=pipe_cfg.get("state_ttl_days", 14)
    )

    # ── Stage 1: 多源采集 (Collection) ────────────────
    all_items = []
    collectors = []

    # 注册已启用的采集器
    if coll_cfg.get("rss", {}).get("enabled"):
        collectors.append(RSSCollector(feeds=coll_cfg["rss"]["feeds"]))
    
    if coll_cfg.get("jina_web", {}).get("enabled"):
        collectors.append(JinaCollector(urls=coll_cfg["jina_web"]["urls"]))

    if coll_cfg.get("arxiv", {}).get("enabled"):
        c = coll_cfg["arxiv"]
        collectors.append(ArxivCollector(categories=c["categories"], max_results=c.get("max_results", 15)))

    if coll_cfg.get("github", {}).get("enabled"):
        c = coll_cfg["github"]
        collectors.append(GitHubCollector(languages=c["languages"], topics=c["topics"], min_stars=c.get("min_stars", 50)))

    if coll_cfg.get("hackernews", {}).get("enabled"):
        c = coll_cfg["hackernews"]
        collectors.append(HackerNewsCollector(keywords=c["keywords"], min_score=c.get("min_score", 50)))

    if coll_cfg.get("reddit", {}).get("enabled"):
        c = coll_cfg["reddit"]
        collectors.append(RedditCollector(subreddits=c.get("subreddits"), min_score=c.get("min_score", 100)))

    # 并发执行采集
    logger.info(f"🚀 开始从 {len(collectors)} 个渠道采集情报...")
    tasks = [c.collect() for c in collectors]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, res in enumerate(results):
        if isinstance(res, Exception):
            logger.error(f"❌ 采集器 {collectors[i].__class__.__name__} 运行异常: {res}")
        elif res:
            all_items.extend(res)

    if not all_items:
        logger.info("📭 本次运行未采集到任何原始数据。")
        return

    # ── Stage 2: 去重过滤 (Deduplication) ────────────────
    # 使用最新的 ID + Title 归一化去重逻辑
    fresh_items = deduper.filter(all_items)
    if not fresh_items:
        logger.info("♻️ 所有采集到的资讯均为重复内容，跳过后续步骤。")
        return

    # ── Stage 3: LLM 评估与总结 (Scoring) ────────────────
    # 限制处理总量，避免 Token 爆炸
    limit = pipe_cfg.get("max_dispatch", 10)
    target_items = fresh_items[:limit * 2] # 稍微多给一点，以便打分后筛选
    
    scorer = LLMScorer(
        score_threshold=pipe_cfg.get("score_threshold", 8.5),
        provider=config.get("llm", {}).get("provider", "deepseek"),
        concurrency=config.get("llm", {}).get("concurrency", 5)
    )
    
    logger.info(f"🧠 正在对 {len(target_items)} 条新资讯进行 AI 深度评估...")
    processed_items = await scorer.score_batch(target_items)

    # ── Stage 4: 结果分发 (Dispatching) ────────────────
    # 仅推送达到分数门槛的内容
    high_value = [i for i in processed_items if i.score >= scorer.score_threshold]
    high_value.sort(key=lambda x: x.score, reverse=True)
    high_value = high_value[:limit] # 最终推送到终端的数量限制

    if not high_value:
        logger.info(f"📉 经过评估，没有资讯达到设定门槛 ({scorer.score_threshold} 分)。")
    else:
        # 获取 Webhook URL (环境变量优先级最高)
        wecom_url = os.getenv("WECOM_WEBHOOK_URL") or config.get("dispatchers", {}).get("wecom", {}).get("webhook_url")
        
        if wecom_url and wecom_url != "YOUR_WECOM_WEBHOOK_URL":
            dispatcher = WeComDispatcher(webhook_url=wecom_url)
            await dispatcher.dispatch(high_value)
            logger.info(f"✅ 已成功推送 {len(high_value)} 条高价值情报至企业微信。")
        else:
            logger.warning("⚠️ 未配置有效的企业微信 Webhook URL，跳过推送环节。")

    # ── Stage 5: 状态保存 (Persistence) ────────────────
    # 无论是否达到分发门槛，只要是“处理过”的 fresh_items 都标记为已读
    deduper.save_state(fresh_items)
    logger.info("💾 去重状态已更新。Pipeline 运行结束。")

if __name__ == "__main__":
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        logger.info("👋 用户手动停止。")
    except Exception as e:
        logger.critical(f"🚨 Pipeline 发生未捕获的严重错误: {e}", exc_info=True)
