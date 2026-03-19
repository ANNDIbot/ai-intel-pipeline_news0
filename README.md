# 🤖 AI Intelligence Pipeline

> 分布式抓取 + 智能化去噪 + 零成本部署
> 每天自动推送高价值 AI 情报，由 LLM 担任"总编辑"。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions (Cron)                     │
│                  每天 10:00 & 22:00 (北京时间)               │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │        信号采集层 (Antennas)      │
          │  ArXiv · RSS · HackerNews · GitHub│
          └────────────────┬────────────────┘
                           │ ~100 raw items
          ┌────────────────▼────────────────┐
          │        去重过滤层 (Dedup)         │
          │   last_seen.json → 剔除已推送     │
          └────────────────┬────────────────┘
                           │ ~30–50 fresh items
          ┌────────────────▼────────────────┐
          │      智能过滤层 (LLM Brain)       │
          │  1–10 评分 · key_insight · 阈值  │
          └────────────────┬────────────────┘
                           │ score ≥ 7 only
          ┌────────────────▼────────────────┐
          │      交互推送层 (Messenger)       │
          │    Telegram · 飞书 · 企业微信     │
          └─────────────────────────────────┘
```

---

## 快速开始

### 1. Fork 或克隆本仓库（建议设为 Private）

```bash
git clone https://github.com/yourname/ai-intel-pipeline
cd ai-intel-pipeline
```

### 2. 配置 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加：

| Secret 名称 | 说明 | 必填 |
|---|---|---|
| `LLM_PROVIDER` | `openai` / `anthropic` / `gemini` / `deepseek` | ✅ |
| `OPENAI_API_KEY` | OpenAI API Key | 按 provider |
| `ANTHROPIC_API_KEY` | Anthropic API Key | 按 provider |
| `GEMINI_API_KEY` | Google Gemini API Key | 按 provider |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 按 provider |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 二选一 |
| `TELEGRAM_CHAT_ID` | 频道或群组 Chat ID | 二选一 |
| `FEISHU_WEBHOOK_URL` | 飞书群机器人 Webhook URL | 二选一 |

### 3. 启用 GitHub Actions

进入 **Actions** 标签页，点击 "Enable Actions"。

Pipeline 会在 **北京时间每天 10:00 和 22:00** 自动运行。
也可手动触发：Actions → AI Intel Pipeline → Run workflow。

### 4. 本地调试

```bash
# 安装依赖（纯 stdlib，几乎无额外依赖）
pip install -r requirements.txt

# 设置环境变量
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...

# 运行
cd src && python main.py
```

---

## 模块说明

### 信号采集层

| 采集器 | 数据源 | 频率 | API Key |
|---|---|---|---|
| `ArxivCollector` | cs.CL + cs.AI + cs.LG | 每次运行 | 不需要 |
| `RSSCollector` | OpenAI/Anthropic/DeepMind 博客 | 每次运行 | 不需要 |
| `HackerNewsCollector` | HN Top Stories (关键词过滤) | 每次运行 | 不需要 |
| `GitHubCollector` | GitHub Search (7天内新星项目) | 每次运行 | 可选（提高限速） |

### 智能过滤层

LLM Scorer 的打分 prompt 要求模型返回结构化 JSON：

```json
{
  "score": 8.5,
  "key_insight": "首个在推理时无需额外算力的自修正架构",
  "reasoning": "解决了 chain-of-thought 的核心效率瓶颈，...",
  "tags": ["architecture", "inference", "reasoning"]
}
```

只有 `score ≥ 7.0` 的条目才会进入推送队列。

### 推送格式示例（Telegram）

```
🤖 AI Intelligence Digest

🔴 [9.2] DeepSeek-R2: Reasoning Without Chain-of-Thought Overhead
↳ 首个在推理时无需额外算力的自修正架构
📎 ArXiv/cs.AI → arxiv.org/abs/2506.XXXXX

🟠 [7.8] Anthropic releases Claude 4 with extended context window
↳ Context window 扩展至 500K tokens，支持整本代码库分析
📎 Anthropic Blog → anthropic.com/news/...
```

---

## 自定义配置

编辑 `config/config.yml`：

```yaml
pipeline:
  score_threshold: 7.5   # 提高门槛，减少推送量

collectors:
  arxiv:
    categories:
      - cs.RO   # 也关注机器人学
  hackernews:
    min_score: 100   # 只看高分帖
```

---

## 状态持久化

`state/last_seen.json` 存储所有已处理条目的 ID，通过 **GitHub Actions Cache** 跨 run 持久化。

TTL 默认 7 天 — 超过 7 天的 ID 会被清除（避免 state 文件无限增长）。

---

## 费用估算

| 组件 | 费用 |
|---|---|
| GitHub Actions | 免费（公共/私有仓库每月 2000 分钟） |
| ArXiv / HN / RSS | 免费 |
| GitHub API | 免费（60 req/hr 未认证） |
| LLM 打分（GPT-4o-mini，~50 items/天） | ≈ $0.01–0.05/天 |
| Telegram Bot | 免费 |
| 飞书 Webhook | 免费 |

**每月总成本：< ¥5**

---

## 扩展方向

- 添加 Reddit `r/MachineLearning` 采集器（需 Reddit API key）
- 添加企业微信机器人 Dispatcher
- 将 `state/` 改为 Git commit，实现完整历史追溯
- 添加每周摘要模式（Sunday digest）
- 支持按标签订阅（用户指定只推送特定 tag）

---

## License

MIT
