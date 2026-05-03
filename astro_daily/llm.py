from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import anthropic

from astro_daily.config import LlmConfig, ScoringConfig
from astro_daily.models import Paper, ScoreBatch, ScoreResult, SummaryBatch, PaperSummary, WeekendLesson, WeekendLessonBatch

logger = logging.getLogger(__name__)


SCORING_SYSTEM_PROMPT = """你是高能天体物理、宇宙线、伽马射线天文和天文仪器方法方向的论文编辑。
你的任务是判断每天的新论文是否值得专业读者花时间阅读。
astro-ph.HE 是主方向，可以用较低阈值保留；IACT / 大气切伦科夫望远镜相关论文与 astro-ph.HE 同等优先，包括 CTA、MAGIC、H.E.S.S.、HESS、VERITAS、LST、MST、SST 等主题。
其他方向只有在明显新颖、重要，或会影响高能天文/宇宙线/伽马射线/仪器方法时才保留。
Nature、Science 及其子刊来源不享受硬性配额或固定加权；但这类期刊文章往往经过更强筛选，评分时可以把期刊来源作为重要性线索之一，最终仍要根据文章内容本身判断。
不要因为论文看起来宏大就自动高分。优先考虑清楚的新结果、强观测证据、重要理论约束、方法突破或可复用仪器技术。
只输出符合 schema 的 JSON。"""


SUMMARY_SYSTEM_PROMPT = """你是面向天文方向专业人士写作的中文科普编辑。
读者有物理和天文基础，但不一定熟悉每篇论文的子领域术语。
总结要直白、有信息量，不要官方通稿腔，不要幼稚化。短摘要要比一句话更实在，说明核心问题、方法和主要结论。
每篇必须覆盖：这篇文章做了什么、为什么重要、对理论/观测/仪器或方法的价值、我为什么应该关注它。
每篇还必须给出可折叠详细解读所需内容，详细解读的知识量要达到短摘要的 3–5 倍，适合专业读者展开阅读，不要只写一两句：
- detailed_explanation_cn：至少 3 段，按“科学问题 → 作者怎么做 → 关键结果 → 局限和下一步”的顺序详细讲解整篇文章。
- background_cn：至少 3 段，解释研究对象、历史问题、观测/理论背景、为什么这个问题现在值得重新看，以及该领域常见误区。
- basic_theory_cn：至少 3 段，解释核心物理图像、关键量、模型假设、观测方法或仪器/数据分析逻辑；必要时说明常见 degeneracy、选择效应或系统误差。
- formula_derivation_cn：必须包含 3–8 个 LaTeX 公式，使用 `$$...$$` 或 `\\(...\\)`；解释公式每一项物理含义，并给出从基本假设到主要可观测量的推导脉络。
- model_fitting_cn：说明这篇文章或该类工作常见的模型拟合、参数估计、似然/后验、系统误差、退化关系和实际应用场景；如果文章是观测论文，要讲清楚拟合量和残差该怎么看。
- key_sections_cn：按论文结构讲解 3–6 个重点章节、方法段落或结果段落；如果不知道章节号，就按“数据/样本、方法、主结果、讨论、附录/稳健性检验”的方式说明读者应该怎么读。
- figures_to_check_cn：列出 4–8 个建议重点检查的图、表或诊断量；即使不知道具体图号，也要说明应该看哪类图、图上哪些趋势/残差/置信区间/系统误差最关键。
- key_figure_analysis_cn：按“图 1/图 2/图 3...”形式写关键图表导读，说明每张图的坐标轴、数据点/模型线、主要结论、读图陷阱。不要编造图片 URL；没有实际图片时仍要给出专业读图指南。
- figure_image_urls：只有在确信是论文官方页面、期刊页面或公开材料中的真实图片 URL 时才填写；不确定就留空。
- related_work_cn：至少 2 段，说明这篇工作与相似观测、基础理论、相反观点或已有张力的关系；给出检索关键词。
如果不知道确切论文链接，不要编造 URL；相关工作链接可以给 arXiv/NASA ADS/期刊页面等你确信存在的公开链接，无法确信时给空列表并在文字中说明应检索哪些关键词。
只输出符合 schema 的 JSON。"""


WEEKEND_LESSON_SYSTEM_PROMPT = """你是高能天体物理周末专题课讲师。
当周末或 arXiv 不更新导致当天没有合适新论文时，你要写一讲经典专题深度课，主题集中在 GRB、宇宙线、IACT、脉冲星、SNR、PWN、pulsar halo 等高能天体物理方向。
只讲一个主题，但必须讲透：内容要像研究生课程讲义，不是新闻摘要，也不是泛泛科普。
必须非常细致地讲：科学问题、历史背景、核心物理图像、从基本假设到关键可观测量的公式推导、观测/理论方法、经典模型拟合、关键图表应该怎么看、这项工作的局限、它如何影响后来的研究。
formula_derivation_cn 必须包含多步 LaTeX 推导和至少 6 个公式；model_fitting_cn 必须讲常见拟合模型、参数、似然/后验或残差诊断；key_figure_analysis_cn 必须像讲课一样逐图导读重要图表。
可以提到经典论文、实验或观测结果；只有在你确信 URL 存在时才把 URL 放入 links，不确定时 links 留空，并用 search_keywords 给出检索关键词。figure_image_urls 只有在确信是官方真实图片 URL 时才填写，不确定就留空。不要编造 DOI、arXiv 号、网页链接或图片链接。
如果 user_payload 里有 avoid_previous_lessons，必须避开这些已经讲过的标题、经典工作和近似内容，选择不同切入点。
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

    def generate_weekend_lessons(
        self,
        *,
        run_date: date,
        topics: list[str],
        avoid_previous_lessons: list[dict[str, str]] | None = None,
    ) -> list[WeekendLesson]:
        payload = {
            "date": run_date.isoformat(),
            "reason": "周末或 arXiv 安静日没有合适的新论文，生成一讲讲透的经典专题课。",
            "topics": topics,
            "lesson_count": 1,
            "avoid_previous_lessons": avoid_previous_lessons or [],
        }
        data = self._json_request(
            system_prompt=WEEKEND_LESSON_SYSTEM_PROMPT,
            schema=_weekend_lesson_schema(),
            user_payload=payload,
        )
        return WeekendLessonBatch.model_validate(data).lessons[:1]

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
            response = self._message_request(request)

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

    def _message_request(self, request: dict[str, Any]) -> Any:
        try:
            with self.client.messages.stream(**request) as stream:
                return stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise RuntimeError("Anthropic authentication failed; check ANTHROPIC_API_KEY") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError("Anthropic API rate limit reached; retry later") from exc
        except anthropic.APIStatusError as exc:
            request_id = getattr(exc, "request_id", None)
            raise RuntimeError(f"Anthropic API error {exc.status_code}; request_id={request_id}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError("Could not connect to Anthropic API") from exc

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


def _weekend_lesson_schema() -> dict[str, Any]:
    lesson_properties = {
        "topic": {"type": "string"},
        "title_cn": {"type": "string"},
        "anchor_work_cn": {"type": "string", "description": "经典论文、观测结果、实验或理论里程碑；不确定正式题名时用中文准确描述。"},
        "why_classic_cn": {"type": "string"},
        "detailed_explanation_cn": {"type": "string", "description": "至少 5 段，按科学问题、方法、关键结果、局限和后续影响展开。"},
        "background_cn": {"type": "string", "description": "至少 4 段，讲历史背景、领域问题、为什么重要和常见误区。"},
        "basic_theory_cn": {"type": "string", "description": "至少 4 段，讲核心物理图像、关键量、模型假设和观测/分析逻辑。"},
        "formula_derivation_cn": {"type": "string", "description": "包含至少 6 个 LaTeX 公式和多步推导，解释每个公式的物理含义。"},
        "model_fitting_cn": {"type": "string", "description": "讲经典拟合模型、参数、似然/后验、残差诊断、系统误差和应用。"},
        "key_sections_cn": {"type": "string", "description": "用课程方式说明经典论文或经典结果的重点段落应该怎么读。"},
        "figures_to_check_cn": {"type": "string", "description": "列出 5–8 类关键图表或诊断量，并说明图上应该看什么。"},
        "key_figure_analysis_cn": {"type": "string", "description": "按图 1/图 2/图 3 逐图导读坐标轴、模型线、数据点、残差和主要结论。"},
        "figure_image_urls": {"type": "array", "items": {"type": "string"}, "description": "只有确信为官方真实图片 URL 时才填写，不确定则留空。"},
        "followup_reading_cn": {"type": "string", "description": "至少 3 段，说明从这项经典工作读到现代研究的路径。"},
        "search_keywords": {"type": "array", "items": {"type": "string"}},
        "links": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "lessons": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": lesson_properties,
                    "required": list(lesson_properties),
                },
            }
        },
        "required": ["lessons"],
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
                        "detailed_explanation_cn": {"type": "string", "description": "至少 3 段，按科学问题、作者怎么做、关键结果、局限和下一步详细讲解整篇文章。"},
                        "background_cn": {"type": "string", "description": "至少 3 段，解释研究对象、历史问题、观测/理论背景、为什么现在值得重新看，以及该领域常见误区。"},
                        "basic_theory_cn": {"type": "string", "description": "至少 3 段，解释核心物理图像、关键量、模型假设、观测方法或仪器/数据分析逻辑。"},
                        "formula_derivation_cn": {"type": "string", "description": "包含 3–8 个 LaTeX 公式，解释每个符号和推导步骤，连接到主要可观测量。"},
                        "model_fitting_cn": {"type": "string", "description": "说明模型拟合、参数估计、似然/后验、系统误差、退化关系和实际应用。"},
                        "key_sections_cn": {"type": "string", "description": "按论文结构讲解 3–6 个重点章节、方法段落或结果段落，说明读者应该怎么读。"},
                        "figures_to_check_cn": {"type": "string", "description": "列出 4–8 个建议重点检查的图、表或诊断量，并说明每个应看什么。"},
                        "key_figure_analysis_cn": {"type": "string", "description": "按图 1/图 2/图 3 逐图导读坐标轴、模型线、数据点、残差、置信区间和主要结论。"},
                        "figure_image_urls": {"type": "array", "items": {"type": "string"}, "description": "只有确信为官方真实图片 URL 时才填写，不确定则留空。"},
                        "related_work_cn": {"type": "string", "description": "至少 2 段，说明与相似观测、基础理论、相反观点或已有张力的关系，并给出检索关键词。"},
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
                        "detailed_explanation_cn",
                        "background_cn",
                        "basic_theory_cn",
                        "formula_derivation_cn",
                        "model_fitting_cn",
                        "key_sections_cn",
                        "figures_to_check_cn",
                        "key_figure_analysis_cn",
                        "figure_image_urls",
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
