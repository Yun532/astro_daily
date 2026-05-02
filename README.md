# astro-daily

每天自动抓取天文方向新论文，优先筛选高能天体物理相关内容，用 Claude 评分并生成中文解读，保存日报 Markdown/HTML，并可通过企业微信群机器人推送 Markdown 摘要。

写作定位：面向天文/物理专业读者的科普式总结。不会写成少儿科普，也不会写成官方通稿；会补充必要背景，但保留足够专业信息。

## 功能

- 数据源
  - arXiv 主方向：`astro-ph.HE`
  - arXiv 辅方向：`astro-ph.IM` / `astro-ph.GA` / `astro-ph.CO` / `astro-ph.SR` / `astro-ph.EP`
  - Nature Astronomy RSS
  - Nature astronomy and astrophysics 主题 RSS
- 筛选策略
  - `astro-ph.HE` 权重最高，推荐阈值较低
  - IACT / 大气切伦科夫望远镜相关论文与 HE 同等优先，包括 CTA、MAGIC、H.E.S.S.、VERITAS、LST 等
  - 其他非 HE 方向必须明显新颖、重要，或对高能天文 / 宇宙线 / 伽马射线 / 仪器方法有影响才保留
- Claude LLM 评分
  - `novelty_score`
  - `importance_score`
  - `relevance_to_me`
  - `final_score`
  - `keep`
- 输出
  - `daily_reports/YYYY-MM-DD.md`
  - `docs/reports/YYYY-MM-DD.html`：由 Markdown 自动转换出的 HTML 报告，用于企业微信摘要跳转或静态托管
  - 每篇论文包含可折叠详细解读：背景知识、基础理论/方法、建议重点查看的图表、强相关工作链接
  - 企业微信 Markdown 摘要：自动压缩 Top 3–5 篇，控制在安全长度内
  - `seen_papers.json`
  - 可选企业微信群机器人推送
- 支持 `--dry-run`
- 支持 cron / Windows Task Scheduler 定时运行

## 环境要求

- Python 3.10+
- Anthropic API key
- 企业微信群机器人 Webhook（仅在启用微信推送时需要）

## 安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

复制环境变量模板：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```text
ANTHROPIC_API_KEY=你的 Anthropic API key
WECOM_WEBHOOK_URL=你的企业微信群机器人 Webhook
```

如果使用本地 Anthropic-compatible 代理（例如 cc switch），可以改用：

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8317
ANTHROPIC_AUTH_TOKEN=你的代理 token
ANTHROPIC_MODEL=gpt-5.5
ANTHROPIC_API_MODE=compatible
```

`ANTHROPIC_AUTH_TOKEN` 会作为 Anthropic SDK 的 API key 使用；`ANTHROPIC_MODEL` 会覆盖 `config.yaml` 里的模型名。密钥只从 `.env` 读取，不要写进 `config.yaml` 或代码。

企业微信群机器人推送使用 Markdown 消息，`WECOM_WEBHOOK_URL` 只写入 `.env`，不要写进代码或提交到仓库。

主要运行参数在 `config.yaml`：

```yaml
sources:
  arxiv:
    days_back: 3
    primary:
      - category: astro-ph.HE
        max_results: 80
    secondary:
      - category: astro-ph.IM
        max_results: 25
  rss:
    feeds:
      - name: Nature Astronomy
        url: https://www.nature.com/natastron.rss

site_base_url: 你的静态站点根地址

publish:
  enabled: false
  provider: github_pages
  mode: git_push
  repo_url:
  branch: main
  docs_dir: docs
  commit_message_template: Publish Astro Daily report {date}
  require_success_before_push: true

wechat:
  enabled: true
```

`site_base_url` 用来拼接完整报告链接：`{site_base_url}/reports/YYYY-MM-DD.html`。如果你不想推送微信，把 `wechat.enabled` 改成 `false`。

`publish.enabled` 默认是 `false`，因此不会自动提交或推送 GitHub。启用 GitHub Pages 发布前，需要先创建 GitHub 仓库，并确保本机 `git push` 到该仓库可用。

## 运行

查看帮助：

```bash
python -m astro_daily --help
```

测试抓取数据源，不调用 LLM：

```bash
python -m astro_daily test-fetch
```

完整 dry-run：

```bash
python -m astro_daily run --dry-run
```

兼容入口也支持：

```bash
python main.py --dry-run
```

Dry-run 会抓取、评分、生成 Markdown/HTML 报告，并打印完整微信摘要文本和发布计划，但不会：

- 更新 `seen_papers.json`
- 推送 GitHub
- 推送微信

正式运行：

```bash
python -m astro_daily run
```

指定日期：

```bash
python -m astro_daily run --date 2026-05-02
```

企业微信群机器人 dry-run 会打印将要发送的 JSON payload；正式运行会打印企业微信 API 返回值，`errcode != 0` 时直接报错。

## GitHub Pages 发布完整报告

完整网页版报告会生成到：

```text
docs/reports/YYYY-MM-DD.html
```

推荐把 GitHub Pages 配置为从 `main` 分支的 `/docs` 目录发布。新建仓库后：

1. 在 GitHub 创建仓库，例如 `astro-daily`。
2. 在本机把项目初始化为 git 仓库并添加远程 `origin`。
3. 在 GitHub 仓库 Settings → Pages 中选择 `main` 分支 `/docs` 目录。
4. 修改 `config.yaml`：

```yaml
site_base_url: https://你的用户名.github.io/astro-daily
publish:
  enabled: true
  provider: github_pages
  mode: git_push
  repo_url: https://github.com/你的用户名/astro-daily.git
  branch: main
  docs_dir: docs
  require_success_before_push: true
```

启用后，正式运行会只提交并推送当天的 `docs/reports/YYYY-MM-DD.html`。如果发布失败，程序不会继续推送企业微信，也不会更新 `seen_papers.json`。

`claude-wechat-channel` 暂未接入；等该工具安装并确认接口形式后，应作为独立发送适配器加入。当前稳定路径是：GitHub Pages 承载完整网页，企业微信群机器人发送摘要和完整报告链接。

## 输出文件

- `daily_reports/YYYY-MM-DD.md`：每日 Markdown 报告
- `docs/reports/YYYY-MM-DD.html`：从 Markdown 自动转换的 HTML 报告，包含 `<meta charset="utf-8">`、基础排版样式和可点击链接
- `seen_papers.json`：已推送论文记录，用于避免重复推送

默认 `.gitignore` 会忽略这两个生成物。如果你想把日报纳入版本控制，可以从 `.gitignore` 删除 `daily_reports/`。

## cron 设置

Linux / macOS 示例：每天早上 08:17 运行。

```cron
17 8 * * * cd /path/to/astro-daily && /path/to/astro-daily/.venv/bin/python -m astro_daily run >> astro_daily.log 2>&1
```

不要把时间都设在整点，避免和大量定时任务同时触发。

## Windows Task Scheduler

在“任务计划程序”中新建任务：

- Program/script:

```text
powershell.exe
```

- Add arguments（先用 11:30 dry-run 验证，不真实推送）：

```text
-NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'E:\astro-daliy'; & '.\.venv\Scripts\python.exe' -m astro_daily run --dry-run --config 'E:\astro-daliy\config.yaml' >> 'E:\astro-daliy\astro_daily.log' 2>&1"
```

- Start in:

```text
E:\astro-daliy
```

确认报告质量和微信配置后，再把命令里的 `run --dry-run` 改成 `run` 用于真实推送和更新 `seen_papers.json`。

## 筛选逻辑

Claude 会先给每篇论文打分，但最终是否保留还会经过本地阈值策略：

- `astro-ph.HE` 和 IACT / 大气切伦科夫望远镜相关论文：阈值较低，并有 HE 级别加权
- 其他非 HE：阈值更高，并要求 `relevance_to_me` 达到最低要求

这样可以避免模型偶尔把泛天文热点文章过度推荐。

## Claude API 说明

本项目使用官方 Anthropic Python SDK：

```python
import anthropic
client = anthropic.Anthropic()
```

默认模型是：

```text
claude-opus-4-7
```

官方 Claude 模型请求使用 adaptive thinking 和结构化 JSON 输出；不会使用 OpenAI-compatible shim，也不会使用 `temperature` / `top_p` / `top_k`。

如果设置了 `ANTHROPIC_BASE_URL` 或非 `claude-` 模型名，程序会自动进入兼容模式：不发送 `thinking`、`output_config` 和 prompt-cache 参数，改用普通 JSON 提示，便于本地代理转发到其他模型。

稳定系统提示在官方 Claude 模式下会启用 prompt caching，日期和论文列表放在用户消息中，避免破坏缓存前缀。

## 测试

运行单元测试：

```bash
pytest
```

建议首次配置后依次运行：

```bash
python -m astro_daily test-fetch
python main.py --dry-run
pytest
```

## 常见问题

### `ANTHROPIC_API_KEY is required`

`.env` 没有配置 `ANTHROPIC_API_KEY`，或运行任务的工作目录不正确。确认命令是在项目根目录执行。

### 微信没有推送

检查：

1. `config.yaml` 中 `wechat.enabled: true`
2. `.env` 中 `WECOM_WEBHOOK_URL` 已设置
3. 不是 `--dry-run`
4. 企业微信群机器人 Webhook 可用，且企业微信 API 返回 `errcode: 0`

### RSS 抓取失败

Nature 的 RSS endpoint 可能会调整。RSS URL 都在 `config.yaml`，可以直接替换。

### arXiv 抓取为空

可能当天没有对应分类新论文，或 `days_back` 太小。可以在 `config.yaml` 增大 `sources.arxiv.days_back`。

## 目录结构

```text
astro_daily/
  cli.py
  config.py
  llm.py
  models.py
  pipeline.py
  report.py
  scoring.py
  seen.py
  summarizer.py
  sources/
    arxiv.py
    rss.py
src/
  push_wecom_bot.py
  report_html.py
  wechat_summary.py
tests/
docs/
  reports/
config.yaml
requirements.txt
.env.example
```
