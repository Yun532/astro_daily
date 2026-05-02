from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import anthropic

from astro_daily.config import LlmConfig, ScoringConfig
from astro_daily.models import Paper, ScoreBatch, ScoreResult, SummaryBatch, PaperSummary

logger = logging.getLogger(__name__)


SCORING_SYSTEM_PROMPT = """你是高能天体物理、宇宙线、伽马射线天文和天文仪器方法方向的论文编辑。
你的任务是判断每天的新论文是否值得专业读者花时间阅读。
astro-ph.HE 是主方向，可以用较低阈值保留；IACT / 大气切伦科夫望远镜相关论文与 astro-ph.HE 同等优先，包括 CTA、MAGIC、H.E.S.S.、HESS、VERITAS、LST、MST、SST 等主题。
其他方向只有在明显新颖、重要，或会影响高能天文/宇宙线/伽马射线/仪器方法时才保留。
不要因为论文看起来宏大就自动高分。优先考虑清楚的新结果、强观测证据、重要理论约束、方法突破或可复用仪器技术。
只输出符合 schema 的 JSON。"""


SUMMARY_SYSTEM_PROMPT = """你是面向天文方向专业人士写作的中文科普编辑。
读者有物理和天文基础，但不一定熟悉每篇论文的子领域术语。
总结要直白、有信息量，不要官方通稿腔，不要幼稚化。短摘要要比一句话更实在，说明核心问题、方法和主要结论。
每篇必须覆盖：这篇文章做了什么、为什么重要、对理论/观测/仪器或方法的价值、我为什么应该关注它。
每篇还必须给出可折叠详细解读所需内容：背景知识、基础理论或方法脉络、建议读者优先检查的图/诊断图/表格、强相关工作线索。
如果不知道确切论文链接，不要编造 URL；相关工作链接可以给 arXiv/NASA ADS/期刊页面等你确信存在的公开链接，无法确信时给空列表并在文字中说明应检索哪些关键词。
只输出符合 schema 的 JSON。"""


class ClaudePaperAnalyst:
    def __init__(self, config: LlmConfig, *, api_key: str):
        self.config = config
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = anthropic.Anthropic(**client_kwargs)

    def score_papers(
        self,
        papers: list[Paper],
        *,
        run_date: date,
        scoring_config: ScoringConfig,
    ) -> list[ScoreResult]:
        if not papers:
            return []
        payload = {
            "date": run_date.isoformat(),
            "policy": {
                "primary_category": "astro-ph.HE",
                "same_priority_topics": ["IACT", "大气切伦科夫望远镜", "CTA", "MAGIC", "H.E.S.S.", "HESS", "VERITAS", "LST", "MST", "SST"],
                "secondary_rule": "IACT / 大气切伦科夫望远镜相关论文按 HE 同等优先级处理；其他非 HE 方向只有在明显影响高能天文、宇宙线、伽马射线或仪器方法时才保留。",
                "weights": scoring_config.weights.model_dump(),
                "thresholds": {
                    "astro-ph.HE": scoring_config.thresholds.high_energy,
                    "non_he": scoring_config.thresholds.non_he,
                    "non_he_min_relevance": scoring_config.non_he_min_relevance,
                },
            },
            "papers": [_paper_for_prompt(paper) for paper in papers],
        }
        data = self._json_request(
            system_prompt=SCORING_SYSTEM_PROMPT,
            schema=_score_schema(),
            user_payload=payload,
        )
        return ScoreBatch.model_validate(data).scores

    def summarize_papers(self, papers: list[Paper], *, run_date: date) -> list[PaperSummary]:
        if not papers:
            return []
        payload = {
            "date": run_date.isoformat(),
            "papers": [_paper_for_prompt(paper) for paper in papers],
        }
        data = self._json_request(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            schema=_summary_schema(),
            user_payload=payload,
        )
        return SummaryBatch.model_validate(data).summaries

    def _json_request(self, *, system_prompt: str, schema: dict[str, Any], user_payload: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [{"role": "user", "content": self._user_content(schema, user_payload)}],
        }
        if self.config.use_claude_native_features:
            if self.config.prompt_cache:
                request["system"] = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
            else:
                request["system"] = system_prompt
            request["thinking"] = {"type": "adaptive"}
            request["output_config"] = {"effort": self.config.effort, "format": {"type": "json_schema", "schema": schema}}
        else:
            request["system"] = _compatible_system_prompt(system_prompt, schema)
        last_parse_error: json.JSONDecodeError | None = None
        for attempt in range(2):
            if attempt:
                logger.warning("LLM returned malformed JSON; retrying once with stricter JSON instruction")
                request["messages"] = [
                    {
                        "role": "user",
                        "content": self._user_content(
                            schema,
                            {
                                **user_payload,
                                "retry_instruction": "上一轮输出不是合法 JSON。请重新输出严格符合 schema 的单个 JSON 对象，不要包含 Markdown、解释、注释或尾随逗号。",
                            },
                        ),
                    }
                ]
            try:
                response = self.client.messages.create(**request)
            except anthropic.AuthenticationError as exc:
                raise RuntimeError("Anthropic authentication failed; check ANTHROPIC_API_KEY") from exc
            except anthropic.RateLimitError as exc:
                raise RuntimeError("Anthropic API rate limit reached; retry later") from exc
            except anthropic.APIStatusError as exc:
                request_id = getattr(exc, "request_id", None)
                raise RuntimeError(f"Anthropic API error {exc.status_code}; request_id={request_id}") from exc
            except anthropic.APIConnectionError as exc:
                raise RuntimeError("Could not connect to Anthropic API") from exc

            usage = getattr(response, "usage", None)
            if usage:
                logger.info(
                    "Claude usage: input=%s cache_read=%s cache_create=%s output=%s",
                    getattr(usage, "input_tokens", None),
                    getattr(usage, "cache_read_input_tokens", None),
                    getattr(usage, "cache_creation_input_tokens", None),
                    getattr(usage, "output_tokens", None),
                )
            text = next((block.text for block in response.content if block.type == "text"), "")
            if not text:
                raise RuntimeError("LLM returned no JSON text block")
            try:
                return _parse_json_text(text)
            except json.JSONDecodeError as exc:
                last_parse_error = exc
        raise RuntimeError("LLM returned malformed JSON after retry") from last_parse_error

    def _user_content(self, schema: dict[str, Any], user_payload: dict[str, Any]) -> str:
        if self.config.use_claude_native_features:
            return json.dumps(user_payload, ensure_ascii=False)
        return json.dumps(
            {
                "schema": schema,
                "input": user_payload,
                "instruction": "Return only one valid JSON object matching schema. Do not include markdown or commentary.",
            },
            ensure_ascii=False,
        )


def _compatible_system_prompt(system_prompt: str, schema: dict[str, Any]) -> str:
    return "\n".join(
        [
            system_prompt,
            "严格只输出一个 JSON 对象，不要输出 Markdown 代码块、解释、前后缀或自然语言说明。",
            "JSON schema:",
            json.dumps(schema, ensure_ascii=False),
        ]
    )


def _parse_json_text(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _paper_for_prompt(paper: Paper) -> dict[str, Any]:
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "authors": paper.authors[:12],
        "abstract": paper.abstract,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "source": paper.source,
        "category": paper.category,
        "published": paper.published.isoformat() if paper.published else None,
        "tags": paper.tags,
    }


def _score_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "paper_id": {"type": "string"},
                        "novelty_score": {"type": "integer"},
                        "importance_score": {"type": "integer"},
                        "relevance_to_me": {"type": "integer"},
                        "final_score": {"type": "number"},
                        "keep": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "paper_id",
                        "novelty_score",
                        "importance_score",
                        "relevance_to_me",
                        "final_score",
                        "keep",
                        "reason",
                    ],
                },
            }
        },
        "required": ["scores"],
    }


def _summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "paper_id": {"type": "string"},
                        "title_cn": {"type": "string"},
                        "summary_cn": {"type": "string"},
                        "why_important_cn": {"type": "string"},
                        "value_cn": {"type": "string"},
                        "why_care_cn": {"type": "string"},
                        "background_cn": {"type": "string"},
                        "basic_theory_cn": {"type": "string"},
                        "figures_to_check_cn": {"type": "string"},
                        "related_work_cn": {"type": "string"},
                        "similar_work_links": {"type": "array", "items": {"type": "string"}},
                        "foundational_work_links": {"type": "array", "items": {"type": "string"}},
                        "tension_or_opposing_links": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "paper_id",
                        "title_cn",
                        "summary_cn",
                        "why_important_cn",
                        "value_cn",
                        "why_care_cn",
                        "background_cn",
                        "basic_theory_cn",
                        "figures_to_check_cn",
                        "related_work_cn",
                        "similar_work_links",
                        "foundational_work_links",
                        "tension_or_opposing_links",
                    ],
                },
            }
        },
        "required": ["summaries"],
    }
