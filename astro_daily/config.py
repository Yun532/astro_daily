from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


class ArxivCategoryConfig(BaseModel):
    category: str
    max_results: int = Field(default=30, ge=1, le=300)


class ArxivConfig(BaseModel):
    days_back: int = Field(default=3, ge=1, le=30)
    primary: list[ArxivCategoryConfig]
    secondary: list[ArxivCategoryConfig] = Field(default_factory=list)
    fetch_mode: str = "daily_listing"
    backfill_with_category_search: bool = False
    on_demand_backfill_with_category_search: bool = True
    id_list_chunk_size: int = Field(default=100, ge=1, le=300)
    api_request_delay_seconds: float = Field(default=6.0, ge=0, le=120)
    api_retry_attempts: int = Field(default=5, ge=1, le=10)
    api_retry_initial_delay_seconds: float = Field(default=10.0, ge=0, le=300)
    api_retry_max_delay_seconds: float = Field(default=300.0, ge=0, le=1800)
    api_cache_enabled: bool = True
    api_cache_dir: str = ".cache/arxiv_api"
    api_cache_ttl_hours: float = Field(default=24.0, ge=0, le=168)

    @model_validator(mode="after")
    def validate_fetch_mode(self) -> "ArxivConfig":
        if self.fetch_mode not in {"daily_listing", "category_search"}:
            raise ValueError("arxiv fetch_mode must be one of: daily_listing, category_search")
        return self


class RssFeedConfig(BaseModel):
    name: str
    url: str


class RssConfig(BaseModel):
    max_entries_per_feed: int = Field(default=30, ge=1, le=200)
    request_delay_seconds: float = Field(default=3.0, ge=0, le=120)
    retry_attempts: int = Field(default=4, ge=1, le=10)
    retry_initial_delay_seconds: float = Field(default=10.0, ge=0, le=300)
    retry_max_delay_seconds: float = Field(default=300.0, ge=0, le=1800)
    cache_enabled: bool = True
    cache_dir: str = ".cache/rss"
    cache_ttl_hours: float = Field(default=6.0, ge=0, le=168)
    feeds: list[RssFeedConfig] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    arxiv: ArxivConfig
    rss: RssConfig


class ScoringWeights(BaseModel):
    novelty: float = 0.30
    importance: float = 0.35
    relevance: float = 0.35

    @model_validator(mode="after")
    def validate_sum(self) -> "ScoringWeights":
        total = self.novelty + self.importance + self.relevance
        if abs(total - 1.0) > 0.001:
            raise ValueError("scoring weights must sum to 1.0")
        return self


class Thresholds(BaseModel):
    high_energy: float = Field(default=6.2, alias="astro-ph.HE")
    non_he: float = 7.8


class ScoringConfig(BaseModel):
    max_candidates: int = Field(default=120, ge=1, le=300)
    max_papers_per_report: int = Field(default=15, ge=1, le=50)
    daily_content_floor: int = Field(default=3, ge=0, le=10)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    category_boost: dict[str, float] = Field(default_factory=lambda: {"astro-ph.HE": 0.10})
    same_day_target: int = Field(default=5, ge=1, le=20)
    max_backfill_papers: int = Field(default=5, ge=0, le=20)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    non_he_min_relevance: int = Field(default=6, ge=1, le=10)
    supplemental_papers: int = Field(default=3, ge=1, le=10)
    supplemental_max_candidates: int = Field(default=30, ge=1, le=100)
    supplemental_min_final_score: float = Field(default=7.0, ge=0, le=10)
    supplemental_min_relevance: int = Field(default=6, ge=1, le=10)


class LlmConfig(BaseModel):
    model: str = "claude-opus-4-7"
    max_tokens: int = Field(default=16000, ge=256)
    effort: str = "high"
    prompt_cache: bool = True
    summary_parallel_workers: int = Field(default=3, ge=1, le=8)
    base_url: str | None = None
    api_mode: str = "auto"

    @property
    def use_claude_native_features(self) -> bool:
        if self.api_mode == "native":
            return True
        if self.api_mode == "compatible":
            return False
        return self.model.startswith("claude-") and not self.base_url


class ReportConfig(BaseModel):
    output_dir: str = "daily_reports"
    seen_file: str = "seen_papers.json"
    feedback_file: str = "feedback.jsonl"
    classic_papers_file: str = "classic_papers.yaml"
    weekend_syllabus_file: str = "weekend_syllabus.yaml"
    title_prefix: str = "Astro Daily"


class WechatConfig(BaseModel):
    enabled: bool = True
    endpoint_template: str = "https://sctapi.ftqq.com/{sendkey}.send"


class ClawBotConfig(BaseModel):
    enabled: bool = False
    base_url: str = "https://ilinkai.weixin.qq.com"
    credentials_file: str | None = None
    sync_file: str | None = None
    default_recipient: str | None = None
    send_report: bool = False
    poll_enabled: bool = False


class PublishConfig(BaseModel):
    enabled: bool = False
    provider: str = "github_pages"
    mode: str = "git_push"
    repo_url: str | None = None
    branch: str = "main"
    docs_dir: str = "docs"
    commit_message_template: str = "Publish Astro Daily report {date}"
    require_success_before_push: bool = True


class FigureExtractionConfig(BaseModel):
    enabled: bool = False
    tool_path: str = "tools/paperfig"
    cache_dir: str = "figure_cache"
    asset_dir: str = "docs/assets/figures"
    max_figures_per_paper: int = Field(default=6, ge=0, le=10)
    max_figure_candidates_per_paper: int = Field(default=12, ge=1, le=50)
    parallel_workers: int = Field(default=3, ge=1, le=8)
    dpi: int = Field(default=400, ge=72, le=800)
    strict: bool = True
    compose_panel_figures: bool = True
    panel_grid_max_columns: int = Field(default=3, ge=1, le=4)
    panel_grid_max_width_px: int = Field(default=4800, ge=1200, le=12000)


class RunLogConfig(BaseModel):
    enabled: bool = True
    dir: str = "logs"


class Settings(BaseModel):
    sources: SourcesConfig
    scoring: ScoringConfig
    llm: LlmConfig
    report: ReportConfig
    wechat: WechatConfig
    clawbot: ClawBotConfig = Field(default_factory=ClawBotConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    figure_extraction: FigureExtractionConfig = Field(default_factory=FigureExtractionConfig)
    run_log: RunLogConfig = Field(default_factory=RunLogConfig)
    site_base_url: str = "本地HTML报告"
    anthropic_api_key: str | None = None
    root_dir: Path = Field(default_factory=lambda: Path.cwd())

    def require_llm_key(self) -> None:
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is required for LLM scoring and summarization")

    @property
    def seen_path(self) -> Path:
        return self.root_dir / self.report.seen_file

    @property
    def feedback_path(self) -> Path:
        return self.root_dir / self.report.feedback_file

    @property
    def classic_papers_path(self) -> Path:
        return self.root_dir / self.report.classic_papers_file

    @property
    def weekend_syllabus_path(self) -> Path:
        return self.root_dir / self.report.weekend_syllabus_file

    @property
    def report_dir(self) -> Path:
        return self.root_dir / self.report.output_dir


def load_settings(config_path: str | Path = "config.yaml") -> Settings:
    load_dotenv()
    path = Path(config_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    with path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}
    raw.setdefault("llm", {})
    if os.getenv("ANTHROPIC_MODEL"):
        raw["llm"]["model"] = os.getenv("ANTHROPIC_MODEL")
    if os.getenv("ANTHROPIC_BASE_URL"):
        raw["llm"]["base_url"] = os.getenv("ANTHROPIC_BASE_URL")
    if os.getenv("ANTHROPIC_API_MODE"):
        raw["llm"]["api_mode"] = os.getenv("ANTHROPIC_API_MODE")
    raw.setdefault("figure_extraction", {})
    if os.getenv("FIGURE_TOOL_PATH"):
        raw["figure_extraction"]["tool_path"] = os.getenv("FIGURE_TOOL_PATH")
    raw.setdefault("clawbot", {})
    if os.getenv("CLAWBOT_DEFAULT_RECIPIENT"):
        raw["clawbot"]["default_recipient"] = os.getenv("CLAWBOT_DEFAULT_RECIPIENT")
    if os.getenv("CLAWBOT_CREDENTIALS_FILE"):
        raw["clawbot"]["credentials_file"] = os.getenv("CLAWBOT_CREDENTIALS_FILE")
    return Settings(
        **raw,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or None,
        root_dir=path.parent,
    )
