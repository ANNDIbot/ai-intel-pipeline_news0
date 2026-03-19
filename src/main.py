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
    
    deduper = DedupFilter(state_file=Path("state/last_seen.json"), ttl_days=p_cfg.get("state_ttl_days", 14))

    all_items = []
    # 1. RSS
    if c_cfg.get("rss", {}).get("enabled"):
        all_items.extend(await RSSCollector(feeds=c_cfg["rss"]["feeds"]).collect())
    # 2. Arxiv
    if c_cfg.get("arxiv", {}).get("enabled"):
        all_items.extend(await ArxivCollector(categories=c_cfg["arxiv"]["categories"]).collect())
    # 3. GitHub (修复此处参数名)
    if c_cfg.get("github", {}).get("enabled"):
        c = c_cfg["github"]
        all_items.extend(await GitHubCollector(
            languages=c.get("languages"), 
            topics=c.get("topics"), 
            min_stars=c.get("min_stars", 50)
        ).collect())
    # 4. Reddit
    if c_cfg.get("reddit", {}).get("enabled"):
        all_items.extend(await RedditCollector(subreddits=c_cfg["reddit"].get("subreddits")).collect())

    fresh_items = deduper.filter(all_items)
    if not fresh_items:
        return

    scorer = LLMScorer(
        score_threshold=p_cfg.get("score_threshold", 8.5),
        provider=config.get("llm", {}).get("provider", "deepseek")
    )
    processed = await scorer.score_batch(fresh_items[:10])
    high_value = [i for i in processed if i.score >= scorer.score_threshold]

    if high_value:
        url = os.getenv("WECOM_WEBHOOK_URL") or config.get("dispatchers", {}).get("wecom", {}).get("webhook_url")
        if url:
            await WeComDispatcher(webhook_url=url).dispatch(high_value)

    deduper.save_state(fresh_items)

if __name__ == "__main__":
    asyncio.run(run_pipeline())
