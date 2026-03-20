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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("pipeline")

def load_config():
    possible_paths = [Path("config/config.yml"), Path("../config/config.yml")]
    for path in possible_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    sys.exit(1)

async def run_pipeline():
    config = load_config()
    p_cfg = config.get("pipeline", {})
    c_cfg = config.get("collectors", {})
    llm_cfg = config.get("llm", {})

    score_threshold = p_cfg.get("score_threshold", 8.0)
    max_dispatch = p_cfg.get("max_dispatch", 10)

    deduper = DedupFilter(state_file=Path("state/last_seen.json"), ttl_days=p_cfg.get("state_ttl_days", 14))

    all_items = []

    # 1. RSS
    if c_cfg.get("rss", {}).get("enabled"):
        items = await RSSCollector(feeds=c_cfg["rss"]["feeds"]).collect()
        logger.info(f"RSS: 采集到 {len(items)} 条")
        all_items.extend(items)

    # 2. Arxiv
    if c_cfg.get("arxiv", {}).get("enabled"):
        items = await ArxivCollector(categories=c_cfg["arxiv"]["categories"]).collect()
        logger.info(f"ArXiv: 采集到 {len(items)} 条")
        all_items.extend(items)

    # 3. GitHub
    if c_cfg.get("github", {}).get("enabled"):
        c = c_cfg["github"]
        items = await GitHubCollector(
            languages=c.get("languages"),
            topics=c.get("topics"),
            min_stars=c.get("min_stars", 50)
        ).collect()
        logger.info(f"GitHub: 采集到 {len(items)} 条")
        all_items.extend(items)

    # 4. HackerNews（之前漏掉了）
    if c_cfg.get("hackernews", {}).get("enabled"):
        hn_cfg = c_cfg["hackernews"]
        items = await HackerNewsCollector(
            keywords=hn_cfg.get("keywords"),
            min_score=hn_cfg.get("min_score", 80)
        ).collect()
        logger.info(f"HackerNews: 采集到 {len(items)} 条")
        all_items.extend(items)

    # 5. Reddit
    if c_cfg.get("reddit", {}).get("enabled"):
        r_cfg = c_cfg["reddit"]
        items = await RedditCollector(
            subreddits=r_cfg.get("subreddits"),
            min_score=r_cfg.get("min_score", 100)
        ).collect()
        logger.info(f"Reddit: 采集到 {len(items)} 条")
        all_items.extend(items)

    # 6. Jina Web（按需）
    if c_cfg.get("jina_web", {}).get("enabled") and c_cfg["jina_web"].get("urls"):
        items = await JinaCollector(urls=c_cfg["jina_web"]["urls"]).collect()
        logger.info(f"Jina: 采集到 {len(items)} 条")
        all_items.extend(items)

    logger.info(f"采集汇总: 共 {len(all_items)} 条原始数据")

    fresh_items = deduper.filter(all_items)
    if not fresh_items:
        logger.info("无新内容，退出")
        return

    logger.info(f"去重后: {len(fresh_items)} 条待评分")

    # 修复：评分全部新条目，而不是仅前 10 条
    # 限制最大评分数量避免 API 费用过高（最多 50 条）
    to_score = fresh_items[:50]
    scorer = LLMScorer(
        score_threshold=score_threshold,
        provider=llm_cfg.get("provider", "deepseek"),
        concurrency=llm_cfg.get("concurrency", 5)
    )
    processed = await scorer.score_batch(to_score)

    # 按分数降序，取 top max_dispatch 推送
    high_value = sorted(
        [i for i in processed if i.score >= score_threshold],
        key=lambda x: x.score,
        reverse=True
    )[:max_dispatch]

    logger.info(f"高价值内容: {len(high_value)} 条 (阈值 {score_threshold})")

    if high_value:
        url = os.getenv("WECOM_WEBHOOK_URL") or config.get("dispatchers", {}).get("wecom", {}).get("webhook_url")
        if url and url.startswith("http"):
            await WeComDispatcher(webhook_url=url).dispatch(high_value)
        else:
            logger.warning("未配置有效的 WECOM_WEBHOOK_URL，跳过推送")

    # 保存所有新条目（不仅是高分的）以防止重复
    deduper.save_state(fresh_items)

if __name__ == "__main__":
    asyncio.run(run_pipeline())
