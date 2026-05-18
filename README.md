# astro-daily

每天自动抓取天文方向新论文，优先筛选高能天体物理相关内容，用 Claude 评分并生成中文解读，保存日报 Markdown/HTML，并可通过企业微信群机器人推送 Markdown 摘要。

写作定位：面向天文/物理专业读者的科普式总结。不会写成少儿科普，也不会写成官方通稿；会补充必要背景，但保留足够专业信息。

## 功能

- 数据源
  - arXiv 主方向：`astro-ph.HE`
  - arXiv 辅方向：`astro-ph.IM` / `astro-ph.GA` / `astro-ph.CO` / `astro-ph.SR` / `astro-ph.EP`
  - Nature / Nature Astronomy / Nature Physics / Nature Communications RSS
  - Nature astronomy and astrophysics 主题 RSS
  - Science / Science Advances RSS
- 筛选策略
  - `astro-ph.HE` 权重最高，推荐阈值较低
  - IACT / 大气切伦科夫望远镜相关论文与 HE 同等优先，包括 CTA、MAGIC、H.E.S.S.、VERITAS、LST 等
  - 其他非 HE 方向必须明显新颖、重要，或对高能天文 / 宇宙线 / 伽马射线 / 仪器方法有影响才保留
  - Nature / Science 及其重点子刊来源会进入候选池并使用较宽的期刊来源阈值，避免漏掉未上 arXiv 的重要文章
- Claude LLM 评分
  - `novelty_score`
  - `importance_score`
  - `relevance_to_me`
  - `final_score`
  - `keep`
- 输出
  - `daily_reports/YYYY-MM-DD.md`
  - `docs/reports/YYYY-MM-DD.html`：由 Markdown 自动转换出的 HTML 报告，用于企业微信摘要跳转或静态托管
  - 每篇论文包含可折叠详细解读：文章详细讲解、背景知识、基础理论/方法、重点章节阅读指引、建议重点查看的图表、强相关工作链接
  - 可选嵌入论文 verified figures：通过 [Yun532/paper_figure_extractor](https://github.com/Yun532/paper_figure_extractor) 提取图号、图片、caption 和 provenance，再由 LLM 按图表解读价值选择展示
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
FIGURE_TOOL_PATH=C:\path\to\paper_figure_extractor\tools\paperfig
CLAWBOT_DEFAULT_RECIPIENT=your-recipient@im.wechat
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
    days_back: 7
    primary:
      - category: astro-ph.HE
        max_results: 120
    secondary:
      - category: astro-ph.IM
        max_results: 25
  rss:
    feeds:
      - name: Nature
        url: https://www.nature.com/nature.rss
      - name: Nature Astronomy
        url: https://www.nature.com/natastron.rss
      - name: Nature Physics
        url: https://www.nature.com/nphys.rss
      - name: Nature Communications
        url: https://www.nature.com/ncomms.rss
      - name: Science
        url: https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science
      - name: Science Advances
        url: https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv

scoring:
  daily_content_floor: 3

report:
  classic_papers_file: classic_papers.yaml
  weekend_syllabus_file: weekend_syllabus.yaml

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

`scoring.daily_content_floor` 表示每日内容下限。当天通过常规阈值的新论文少于该数量时，程序会先补近期/较早未读的重要论文；仍不足时，从 `classic_papers.yaml` 中选择一篇未精读过的具体经典论文或重要旧文，不会让模型临时编造经典论文候选。

`report.weekend_syllabus_file` 指向 `weekend_syllabus.yaml`。周末运行时，程序会优先从这个课程表里选择下一讲未学过的课程，并把课程标题、系列、章节、前置知识、经典论文和前沿方向作为硬约束传给 LLM。这样周末内容是连续课程，而不是临时主题。

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

## 论文图片提取

可选图片功能依赖独立项目 [Yun532/paper_figure_extractor](https://github.com/Yun532/paper_figure_extractor)。Astro Daily 只使用该工具输出的 verified figures，不嵌入 candidates 中的不确定截图；报告会保留图号、caption、来源置信度和 provenance，并让 LLM 根据“建议重点查看的图表 / 关键图表逐图导读 / 模型拟合”选择最值得展示的图。

配置示例：

```yaml
figure_extraction:
  enabled: true
  tool_path: C:\path\to\paper_figure_extractor\tools\paperfig
  cache_dir: figure_cache
  asset_dir: docs/assets/figures
  max_figures_per_paper: 6
  max_figure_candidates_per_paper: 12
  dpi: 400
  strict: true
```

生成后的图片会复制到 `docs/assets/figures/YYYY-MM-DD/<paper_id>/` 并随 GitHub Pages 报告一起发布；`figure_cache/` 只作为本地缓存，不提交到仓库。

个人微信 ClawBot 可作为企业微信群机器人的补充通道。`claude-code-wechat-channel` 仍可用于扫码登录并生成本机 ClawBot 登录凭据，但日报项目内的可靠发送路径使用直接 ClawBot HTTP 适配器，不依赖 Claude Code 实验 channel 路由。配置示例：

```yaml
clawbot:
  enabled: false
  base_url: https://ilinkai.weixin.qq.com
  default_recipient:
  send_report: false
  poll_enabled: false
```

测试现有报告链接发送，不生成新报告：

```bash
python -m astro_daily test-clawbot-send --dry-run
python -m astro_daily test-clawbot-send --date 2026-05-02
```

诊断微信入站消息：

```bash
python -m astro_daily test-clawbot-poll
```

把微信输入作为一次模型输入并自动回复：

```bash
python -m astro_daily clawbot-chat
```

只处理一轮消息可用于测试：

```bash
python -m astro_daily clawbot-chat --once
```

不要同时运行多个 ClawBot 监听器，包括单独的 `npx claude-code-wechat-channel start`、`test-clawbot-poll` 循环和 `clawbot-chat`；否则消息游标和上下文 token 可能被不同进程消费。当前稳定自动化路径仍然是：GitHub Pages 承载完整网页，企业微信群机器人发送摘要和完整报告链接。

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
-NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\path\to\astro-daily'; & '.\.venv\Scripts\python.exe' -m astro_daily run --dry-run --config '.\config.yaml' >> '.\astro_daily.log' 2>&1"
```

- Start in:

```text
C:\path\to\astro-daily
```

确认报告质量和微信配置后，再把命令里的 `run --dry-run` 改成 `run` 用于真实推送和更新 `seen_papers.json`。

## 筛选逻辑

Claude 会先给每篇论文打分，但最终是否保留还会经过本地阈值策略：

- `astro-ph.HE` 和 IACT / 大气切伦科夫望远镜相关论文：阈值较低，并有 HE 级别加权
- 其他非 HE：阈值更高，并要求 `relevance_to_me` 达到最低要求

这样可以避免模型偶尔把泛天文热点文章过度推荐。

当当天新论文通过阈值数量不足 `scoring.daily_content_floor` 时，日报会明确标注补充内容：

- `今日新文`：确认属于当天 arXiv daily listing 或 RSS 日期的常规推荐。
- `补充推荐`：近期/较早未读的重要论文，不会标成今日论文。
- `经典旧文精读`：来自 `classic_papers.yaml` 的具体经典论文/重要旧文。

`classic_papers.yaml` 的条目字段固定为：

```yaml
- id: li-ma-1983-significance
  title: Analysis methods for results in gamma-ray astronomy
  authors: [T.-P. Li, Y.-Q. Ma]
  year: 1983
  url: https://ui.adsabs.harvard.edu/abs/1983ApJ...272..317L/abstract
  topic: Gamma-ray astronomy statistics
  tags: [gamma-ray astronomy, significance, IACT]
  why_classic_cn: Li-Ma 显著性公式是伽马射线天文 on/off 计数分析的标准工具。
```

`weekend_syllabus.yaml` 用来控制周末课程顺序。条目包含 `id/title_cn/series_id/part_index/planned_parts/topic/anchor_work_cn/prerequisites_cn/lesson_scope_cn/why_classic_cn/classic_paper_ids/modern_directions_cn/search_keywords/links`。程序会跳过 `seen_papers.json` 中已讲过的同标题或同系列同章节，选择下一讲，保证 GRB、TDE、PWN/pulsar halo 按课程推进。

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

Windows 当前机器如果系统临时目录权限受限，推荐使用项目内临时目录并关闭 pytest cache：

```powershell
$env:TMP='E:\astro-daliy\.pytest-tmp'
$env:TEMP='E:\astro-daliy\.pytest-tmp'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
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
  figure_extractor.py
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
