from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

import anthropic

from astro_daily.config import LlmConfig, ScoringConfig
from astro_daily.models import ExtractedFigure, FigureSelection, FigureSelectionBatch, Paper, PaperSummary, ScoreBatch, ScoreResult, SummaryBatch, WeekendLesson, WeekendLessonBatch

logger = logging.getLogger(__name__)


SUMMARY_DEPTH_CONTRACT = {
    "goal": "Make each selected-paper detail section read like a compact graduate reading note, not a news summary.",
    "detail_multiplier": "The collapsible detail should be at least 5-8 times richer than the short summary.",
    "basic_theory_cn": "Write 4-6 paragraphs. Start from the physical picture and prerequisite concepts, then introduce the paper-specific assumptions, key quantities, observational/statistical method, and common degeneracies or systematics.",
    "formula_derivation_cn": (
        "Write a coherent derivation ladder with 6-12 LaTeX formulas. Use steps such as: basic conservation law or radiative/statistical principle; "
        "paper-specific model equation; observable or likelihood; limiting case or scaling relation; physical interpretation. "
        "Define symbols, state assumptions, and explain what each equation lets the reader compute or check. "
        "For observational/instrument papers with few explicit theory equations, derive the relevant flux, response, likelihood, sensitivity, or significance relations instead of leaving this section thin."
    ),
    "model_fitting_cn": "Write 4-6 paragraphs. Include fitted quantities, priors or likelihood/statistic, residual diagnostics, parameter degeneracies, and how the model could fail.",
    "continuity_rule": "The theory and formula sections must bridge from background basics to the actual equations or diagnostics used by the paper; do not jump straight into paper jargon.",
}


WEEKEND_LESSON_DEPTH_CONTRACT = {
    "goal": "Make the weekend lesson resemble the first GRB afterglow lesson: systematic, continuous, and course-like.",
    "course_shape": "Use a foundation-to-frontier arc: motivation, historical context, basic physical picture, multi-step derivation, fitting/diagnostics, figure reading, limitations, and reading path.",
    "basic_theory_cn": "Write 5-8 paragraphs. Build prerequisites gradually and keep a clear boundary with previous or future parts in the same series.",
    "formula_derivation_cn": (
        "Write an 8-14 formula multi-step derivation. Prefer numbered or clearly signposted steps such as 第一/第二/第三步. "
        "Each step should say what assumption is being used, what quantity is being solved for, and how the result connects to the next step. "
        "Include standard limiting cases and observational closure/diagnostic relations when relevant."
    ),
    "model_fitting_cn": "Write 5-8 paragraphs with concrete likelihoods, fitted parameters, posterior/uncertainty interpretation, residual checks, and common systematics.",
    "key_figure_analysis_cn": "Write at least 5 figure-reading entries. Each entry should explain axes, model/data comparison, what to check, and common misreadings.",
    "continuity_rule": "If continuing a series, explicitly state what the previous part covered, what this part adds, and what is intentionally left to the next part.",
}


SCORING_SYSTEM_PROMPT = """你是高能天体物理、宇宙线、伽马射线天文和天文仪器方法方向的论文编辑。
你的任务是判断每天的新论文是否值得专业读者花时间阅读。
astro-ph.HE 是主方向，可以用较低阈值保留；其中伽马射线天文是最高优先级之一，涉及 GeV/TeV 伽马射线、Fermi-LAT、CTA、MAGIC、H.E.S.S.、HESS、VERITAS、LHAASO、HAWC、GRB、AGN/blazar、SNR、PWN、PeVatron、Galactic Center excess 等主题时，应明显提高 relevance_to_me 和 final_score。
IACT / 大气切伦科夫望远镜相关论文与 astro-ph.HE 同等优先，包括 CTA、MAGIC、H.E.S.S.、HESS、VERITAS、LST、MST、SST 等主题。
高能中微子天文学也属于重点兴趣，应比一般 HE 论文更优先，但权重低于伽马射线天文；只有在论文与天体源、高能宇宙线、强子伽马/中微子辐射或多信使高能天体物理明显相关时按重点处理；普通中微子振荡、质量、反应堆/加速器中微子或无天体物理关联的探测器论文不要因此加权。
其他方向只有在明显新颖、重要，或会影响高能天文/宇宙线/伽马射线/中微子天文学/仪器方法时才保留。
Nature、Science 及其子刊来源不享受硬性配额或固定加权；但这类期刊文章往往经过更强筛选，评分时可以把期刊来源作为重要性线索之一，最终仍要根据文章内容本身判断。
不要因为论文看起来宏大就自动高分。优先考虑清楚的新结果、强观测证据、重要理论约束、方法突破或可复用仪器技术。
只输出符合 schema 的 JSON。"""


SUMMARY_SYSTEM_PROMPT = """你是面向天文方向专业人士写作的中文科普编辑。
读者有物理和天文基础，但不一定熟悉每篇论文的子领域术语。
总结要直白、有信息量，不要官方通稿腔，不要幼稚化。短摘要要比一句话更实在，说明核心问题、方法和主要结论。
每篇必须覆盖：这篇文章做了什么、为什么重要、对理论/观测/仪器或方法的价值、我为什么应该关注它。
每篇还必须给出可折叠详细解读所需内容，详细解读的知识量要达到短摘要的 5–8 倍，适合专业读者展开阅读，不要只写一两句：
- detailed_explanation_cn：至少 4 段，按“科学问题 → 作者怎么做 → 关键结果 → 局限和下一步”的顺序详细讲解整篇文章。
- background_cn：至少 4 段，解释研究对象、历史问题、观测/理论背景、为什么这个问题现在值得重新看，以及该领域常见误区。
- basic_theory_cn：至少 4 段，从基础物理图像讲到本文使用的模型假设、关键量、观测方法或仪器/数据分析逻辑；必要时说明常见 degeneracy、选择效应或系统误差。
- formula_derivation_cn：必须包含 6–12 个 LaTeX 公式，使用 `$$...$$`、`\\[...\\]` 或 `\\(...\\)`；要像“推导阶梯”一样从基本假设、守恒律、辐射/统计原理讲到论文中的核心方程、主要可观测量或似然/显著性诊断。解释每个符号、适用条件和物理含义。观测或仪器论文即使原文公式少，也要推导通量、响应、灵敏度、似然、残差或显著性等相关公式，不要让本节变薄。
- model_fitting_cn：至少 4 段，说明这篇文章或该类工作常见的模型拟合、参数估计、似然/后验、系统误差、退化关系和实际应用场景；如果文章是观测论文，要讲清楚拟合量和残差该怎么看。
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
课程可以连续：如果最近课程历史里有同一 series_id 且 next_lesson_suggestions 指向自然续讲，你可以选择同一系列的下一部分；否则开启一个新的短系列。连续同一系列时，必须明确 part_index、planned_parts、previous_context_cn 和 lesson_scope_cn，避免重复上一讲已经覆盖的物理内容。
同一系列建议 2 到 4 讲；连续讲同一课题是允许的，但每一讲必须有清晰边界，例如“动力学”“辐射机制”“观测拟合”“仪器/系统误差”，不要换标题后重复同一套公式和图表。
必须非常细致地讲：科学问题、历史背景、核心物理图像、从基本假设到关键可观测量的公式推导、观测/理论方法、经典模型拟合、关键图表应该怎么看、这项工作的局限、它如何影响后来的研究。
课程的深度要接近研究生讲义：basic_theory_cn 至少 5 段；formula_derivation_cn 必须包含 8–14 个公式，并按“第一步、第二步……”或等价方式连续推导；model_fitting_cn 至少 5 段，必须讲常见拟合模型、参数、似然/后验或残差诊断；key_figure_analysis_cn 必须至少逐图导读 5 类重要图表。
可以提到经典论文、实验或观测结果；只有在你确信 URL 存在时才把 URL 放入 links，不确定时 links 留空，并用 search_keywords 给出检索关键词。figure_image_urls 只有在确信是官方真实图片 URL 时才填写，不确定就留空。不要编造 DOI、arXiv 号、网页链接或图片链接。
如果 user_payload 里有 avoid_previous_lessons，必须避开已经讲过的标题、经典工作和 lesson_scope；只有在作为同一 series_id 的下一讲时，才可以延续同一大主题，并且要说明与上一讲的承接关系和不重复边界。
只输出符合 schema 的 JSON。"""


WEEKEND_LESSON_SECTION_SYSTEM_PROMPT = """你是高能天体物理周末专题课的章节作者。
输入会给出已经选定的课程主题、系列边界、经典工作和已有章节草稿。你的任务是只重写 requested_fields 中指定的课程章节。
章节必须系统、连续、有课程感：先铺基础，再进入公式或方法，不要像新闻摘要，也不要只罗列概念。
公式推导章节必须是一条完整推导链：每一步说明使用的假设、解出的物理量、与下一步的关系，以及最终如何连接到可观测量或诊断量。
拟合和图表章节必须说明实际读论文时怎么检查模型、残差、置信区间、系统误差和图上陷阱。
不要改变课程标题、系列编号、主题边界或经典工作；不要编造 URL。只输出符合 schema 的 JSON。"""


WEEKEND_LESSON_OUTLINE_SYSTEM_PROMPT = """You are a graduate-level high-energy astrophysics course designer.
The final lesson will be written in Chinese, but this step only plans the lesson. Given a selected weekend lesson topic, build a detailed teaching skeleton before any section is expanded.
The skeleton must force a shallow-to-deep path: prerequisite ideas, historical motivation, physical picture, derivation ladder, observational diagnostics, model fitting, figure reading, caveats, and the next lesson boundary.
Do not write the full lesson here. Return only JSON matching the schema. Do not invent URLs, paper identifiers, or image links."""


REPORT_MATH_FORMAT_CONTRACT = """
Math formatting is part of the content contract. Wrap every variable, equation, relation, and symbolic expression in valid LaTeX delimiters: use \\(...\\) for inline math and \\[...\\] for displayed equations. Do not write bare expressions such as E_peak, L_iso, N(E)=..., Γ_min, α, β, or τ_{γγ} in prose. Do not split a LaTeX command across lines, and do not use raw control characters inside math."""

SUMMARY_SYSTEM_PROMPT += REPORT_MATH_FORMAT_CONTRACT
WEEKEND_LESSON_SYSTEM_PROMPT += REPORT_MATH_FORMAT_CONTRACT
WEEKEND_LESSON_SECTION_SYSTEM_PROMPT += REPORT_MATH_FORMAT_CONTRACT


FIGURE_SELECTION_SYSTEM_PROMPT = """你是天体物理论文图表编辑。
你的任务不是挑好看的图，而是从已验证提取出的论文原图中，选择最能支撑日报详细解读的图。
必须优先匹配日报里“建议重点查看的图表”和“关键图表逐图导读”提到的图号、诊断量、坐标轴、模型线、残差、置信区间或系统误差。
只能选择输入 candidates 里真实存在的 fig_id；不要编造图号、图片链接或论文没有的图。
如果候选图与文字解读关系弱，可以少选；如果多张图都重要，按科学价值从高到低排序。
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
        feedback_context: dict[str, Any] | None = None,
    ) -> list[ScoreResult]:
        if not papers:
            return []
        payload = {
            "date": run_date.isoformat(),
            "policy": {
                "primary_category": "astro-ph.HE",
                "same_priority_topics": [
                    "IACT",
                    "大气切伦科夫望远镜",
                    "CTA",
                    "MAGIC",
                    "H.E.S.S.",
                    "HESS",
                    "VERITAS",
                    "LST",
                    "MST",
                    "SST",
                    "high-energy neutrino astronomy with clear astrophysical-source or cosmic-ray context",
                    "IceCube/KM3NeT/Baikal-GVD source or multimessenger neutrino results",
                ],
                "secondary_rule": "IACT / 大气切伦科夫望远镜相关论文按 HE 同等优先级处理；高能中微子方向只有在明显关联天体源、高能宇宙线、强子伽马/中微子辐射或多信使高能天体物理时按重点处理；普通中微子振荡、质量、反应堆/加速器中微子或无天体物理关联的探测器论文不要因为中微子关键词而加权。其他非 HE 方向只有在明显影响高能天文、宇宙线、伽马射线、中微子天文学或仪器方法时才保留。",
                "weights": scoring_config.weights.model_dump(),
                "thresholds": {
                    "astro-ph.HE": scoring_config.thresholds.high_energy,
                    "non_he": scoring_config.thresholds.non_he,
                    "non_he_min_relevance": scoring_config.non_he_min_relevance,
                },
            },
            "papers": [_paper_for_prompt(paper) for paper in papers],
        }
        if feedback_context:
            payload["reader_feedback"] = feedback_context
        data = self._json_request(
            system_prompt=SCORING_SYSTEM_PROMPT,
            schema=_score_schema(),
            user_payload=payload,
            request_type="scoring",
            paper_ids=[paper.paper_id for paper in papers],
        )
        return ScoreBatch.model_validate(data).scores

    def summarize_papers(self, papers: list[Paper], *, run_date: date) -> list[PaperSummary]:
        if not papers:
            return []
        payload = {
            "date": run_date.isoformat(),
            "content_depth_contract": SUMMARY_DEPTH_CONTRACT,
            "papers": [_paper_for_prompt(paper) for paper in papers],
        }
        data = self._json_request(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            schema=_summary_schema(),
            user_payload=payload,
            request_type="summary",
            paper_ids=[paper.paper_id for paper in papers],
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
            "course_policy": {
                "allow_consecutive_parts": True,
                "preferred_series_length": "2-4 lessons",
                "continuation_rule": "You may continue the same series when the next lesson has a distinct scope and naturally follows the recent history.",
                "new_series_rule": "Start a new series if recent lessons do not expose a useful next_lesson_suggestions path, or if continuing would repeat the same physics.",
                "required_boundary": "Use lesson_scope_cn to state exactly what this lesson covers and what it intentionally leaves for other parts.",
            },
            "content_depth_contract": WEEKEND_LESSON_DEPTH_CONTRACT,
            "lesson_count": 1,
            "avoid_previous_lessons": avoid_previous_lessons or [],
        }
        data = self._json_request(
            system_prompt=WEEKEND_LESSON_SYSTEM_PROMPT,
            schema=_weekend_lesson_schema(),
            user_payload=payload,
            request_type="weekend_lesson",
            paper_ids=[],
        )
        lessons = WeekendLessonBatch.model_validate(data).lessons[:1]
        return [self._expand_weekend_lesson_sections(lesson, run_date=run_date) for lesson in lessons]

    def _expand_weekend_lesson_sections(self, lesson: WeekendLesson, *, run_date: date) -> WeekendLesson:
        section_groups = [
            ["detailed_explanation_cn", "background_cn", "basic_theory_cn"],
            ["formula_derivation_cn"],
            [
                "model_fitting_cn",
                "key_sections_cn",
                "figures_to_check_cn",
                "key_figure_analysis_cn",
                "followup_reading_cn",
                "next_lesson_suggestions_cn",
            ],
        ]
        try:
            course_outline = self._generate_weekend_lesson_outline(lesson, run_date=run_date)
        except RuntimeError as exc:
            logger.warning("Weekend lesson outline generation failed: %s", exc)
            course_outline = {}
        expanded = lesson
        for fields in section_groups:
            try:
                updates = self._expand_weekend_lesson_section_group(
                    expanded,
                    run_date=run_date,
                    fields=fields,
                    course_outline=course_outline,
                )
            except RuntimeError as exc:
                logger.warning("Weekend lesson section expansion failed fields=%s: %s", fields, exc)
                continue
            expanded = expanded.model_copy(update={field: updates[field] for field in fields if field in updates})
        return expanded

    def _generate_weekend_lesson_outline(self, lesson: WeekendLesson, *, run_date: date) -> dict[str, Any]:
        payload = {
            "date": run_date.isoformat(),
            "content_depth_contract": WEEKEND_LESSON_DEPTH_CONTRACT,
            "lesson_context": lesson.model_dump(),
            "instruction": (
                "Design the course skeleton first. Keep it specific to this lesson scope, list prerequisite foundations, "
                "then plan the chapter flow and derivation ladder that later section expansion must follow."
            ),
        }
        return self._json_request(
            system_prompt=WEEKEND_LESSON_OUTLINE_SYSTEM_PROMPT,
            schema=_weekend_lesson_outline_schema(),
            user_payload=payload,
            request_type="weekend_lesson_outline",
            paper_ids=[],
        )

    def _expand_weekend_lesson_section_group(
        self,
        lesson: WeekendLesson,
        *,
        run_date: date,
        fields: list[str],
        course_outline: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        payload = {
            "date": run_date.isoformat(),
            "requested_fields": fields,
            "content_depth_contract": WEEKEND_LESSON_DEPTH_CONTRACT,
            "course_outline": course_outline or {},
            "lesson_context": lesson.model_dump(),
            "instruction": (
                "Rewrite only requested_fields. Treat course_outline as the controlling teaching skeleton. "
                "Preserve the chosen course scope and make these fields systematic and course-like. "
                "Do not shorten existing useful content; replace it with a clearer, more coherent chapter."
            ),
        }
        data = self._json_request(
            system_prompt=WEEKEND_LESSON_SECTION_SYSTEM_PROMPT,
            schema=_weekend_lesson_section_schema(fields),
            user_payload=payload,
            request_type="weekend_lesson_section",
            paper_ids=[],
        )
        return {field: str(data.get(field, "")).strip() for field in fields}

    def select_figures_for_paper(
        self,
        *,
        paper: Paper,
        summary: PaperSummary,
        figures: list[ExtractedFigure],
        max_figures: int,
        run_date: date,
    ) -> list[FigureSelection]:
        if not figures or max_figures <= 0:
            return []
        payload = {
            "date": run_date.isoformat(),
            "max_figures": max_figures,
            "paper": _paper_for_prompt(paper),
            "report_sections": {
                "figures_to_check_cn": summary.figures_to_check_cn,
                "key_figure_analysis_cn": summary.key_figure_analysis_cn,
                "model_fitting_cn": summary.model_fitting_cn,
                "detailed_explanation_cn": summary.detailed_explanation_cn,
            },
            "candidates": [_figure_for_prompt(figure) for figure in figures],
        }
        data = self._json_request(
            system_prompt=FIGURE_SELECTION_SYSTEM_PROMPT,
            schema=_figure_selection_schema(),
            user_payload=payload,
            request_type="figure_selection",
            paper_ids=[paper.paper_id],
        )
        return FigureSelectionBatch.model_validate(data).selections[:max_figures]

    def _json_request(
        self,
        *,
        system_prompt: str,
        schema: dict[str, Any],
        user_payload: dict[str, Any],
        request_type: str,
        paper_ids: list[str],
    ) -> dict[str, Any]:
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
        last_error_context = ""
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
                last_error_context = _json_error_context(text, exc.pos)
                logger.warning(
                    "LLM JSON parse failed request_type=%s paper_ids=%s at pos=%s: %s; context=%s",
                    request_type,
                    paper_ids,
                    exc.pos,
                    exc.msg,
                    last_error_context,
                )
        detail = f": {last_parse_error.msg} at pos {last_parse_error.pos}" if last_parse_error else ""
        raise RuntimeError(
            f"LLM returned malformed JSON after retry{detail}; request_type={request_type}; paper_ids={paper_ids}; context={last_error_context}"
        ) from last_parse_error

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


def _json_error_context(text: str, position: int, *, radius: int = 180) -> str:
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    return text[start:end].replace("\r", "\\r").replace("\n", "\\n")


def _parse_json_text(text: str) -> dict[str, Any]:
    try:
        return _loads_json(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return _loads_json(text[start : end + 1])


def _loads_json(text: str) -> dict[str, Any]:
    repaired = _repair_common_json_issues(text)
    candidates = [repaired]
    if repaired != text:
        candidates.append(text)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return _loads_json_with_targeted_repairs(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return json.loads(text)


def _loads_json_with_targeted_repairs(text: str, *, max_repairs: int = 20) -> dict[str, Any]:
    candidate = text
    seen: set[str] = set()
    last_error: json.JSONDecodeError | None = None
    for _attempt in range(max_repairs + 1):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            repaired = _repair_json_error_at_position(candidate, exc)
            if repaired is None or repaired == candidate or repaired in seen:
                break
            seen.add(candidate)
            candidate = repaired
    if last_error is not None:
        raise last_error
    return json.loads(text)


def _repair_json_error_at_position(text: str, exc: json.JSONDecodeError) -> str | None:
    if exc.msg != "Invalid \\escape":
        return None
    slash_index = exc.pos if exc.pos < len(text) and text[exc.pos] == "\\" else text.rfind("\\", 0, exc.pos + 1)
    if slash_index == -1:
        return None
    return text[:slash_index] + "\\" + text[slash_index:]


def _repair_common_json_issues(text: str) -> str:
    repaired = _escape_unescaped_string_control_characters(text)
    repaired = _escape_unescaped_latex_backslashes(repaired)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _escape_unescaped_string_control_characters(text: str) -> str:
    output: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"' and _is_unescaped_quote(text, index):
            in_string = not in_string
            output.append(char)
        elif in_string and char == "\n":
            output.append("\\n")
        elif in_string and char == "\r":
            output.append("\\r")
        elif in_string and char == "\t":
            output.append("\\t")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _escape_unescaped_latex_backslashes(text: str) -> str:
    output: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"' and _is_unescaped_quote(text, index):
            in_string = not in_string
            output.append(char)
            index += 1
            continue
        if in_string and char == "\\":
            next_char = text[index + 1] if index + 1 < len(text) else ""
            after_next = text[index + 2] if index + 2 < len(text) else ""
            if _is_json_escape(next_char, after_next, text[index + 2 : index + 6]):
                output.append(char)
            else:
                output.append("\\\\")
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _is_unescaped_quote(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 0


def _is_json_escape(next_char: str, after_next: str, unicode_digits: str) -> bool:
    if next_char in {'"', "\\", "/"}:
        return True
    if next_char == "u":
        return len(unicode_digits) == 4 and all(char in "0123456789abcdefABCDEF" for char in unicode_digits)
    if next_char in {"b", "f", "n", "r", "t"}:
        return not (after_next.isascii() and after_next.isalpha())
    return False


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
        "updated": paper.updated.isoformat() if paper.updated else None,
        "source_batch_date": paper.source_batch_date.isoformat() if paper.source_batch_date else None,
        "tags": paper.tags,
    }


def _figure_for_prompt(figure: ExtractedFigure) -> dict[str, str]:
    return {
        "fig_id": figure.fig_id,
        "caption": figure.caption,
        "confidence": figure.confidence,
        "source_type": figure.source_type,
        "provenance": figure.provenance,
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
        "series_id": {"type": "string", "description": "Stable lowercase ASCII id for a short course series, e.g. grb-afterglow or iact-methods."},
        "series_title_cn": {"type": "string", "description": "中文系列名，例如 GRB 余辉经典课程。"},
        "part_index": {"type": "integer", "minimum": 1, "description": "本讲是该系列第几讲。"},
        "planned_parts": {"type": "integer", "minimum": 1, "description": "该短系列计划总讲数，通常 2 到 4。"},
        "lesson_scope_cn": {"type": "string", "description": "本讲覆盖边界：讲什么、不讲什么、与同系列其他讲如何区分。"},
        "previous_context_cn": {"type": "string", "description": "如果承接同系列上一讲，说明上一讲已讲什么和本讲如何接上；新系列可说明这是第一讲。"},
        "why_classic_cn": {"type": "string"},
        "detailed_explanation_cn": {"type": "string", "description": "至少 5 段，按科学问题、方法、关键结果、局限和后续影响展开。"},
        "background_cn": {"type": "string", "description": "至少 5 段，讲历史背景、领域问题、为什么重要和常见误区。"},
        "basic_theory_cn": {"type": "string", "description": "至少 5–8 段，讲核心物理图像、关键量、模型假设和观测/分析逻辑。"},
        "formula_derivation_cn": {"type": "string", "description": "包含至少 8 个 LaTeX 公式和连续多步推导，解释每个公式的物理含义、假设和下一步用途。"},
        "model_fitting_cn": {"type": "string", "description": "至少 5 段，讲经典拟合模型、参数、似然/后验、残差诊断、系统误差和应用。"},
        "key_sections_cn": {"type": "string", "description": "用课程方式说明经典论文或经典结果的重点段落应该怎么读。"},
        "figures_to_check_cn": {"type": "string", "description": "列出 5–8 类关键图表或诊断量，并说明图上应该看什么。"},
        "key_figure_analysis_cn": {"type": "string", "description": "按图 1/图 2/图 3 逐图导读坐标轴、模型线、数据点、残差和主要结论。"},
        "figure_image_urls": {"type": "array", "items": {"type": "string"}, "description": "只有确信为官方真实图片 URL 时才填写，不确定则留空。"},
        "followup_reading_cn": {"type": "string", "description": "至少 3 段，说明从这项经典工作读到现代研究的路径。"},
        "next_lesson_suggestions_cn": {"type": "string", "description": "给出同一系列下一讲最自然的 1-3 个方向；如果系列已完结，说明建议切换的新系列。"},
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


def _weekend_lesson_outline_schema() -> dict[str, Any]:
    chapter_properties = {
        "heading_cn": {"type": "string", "description": "Chinese chapter heading."},
        "teaching_goal_cn": {"type": "string", "description": "What this chapter should teach."},
        "key_points_cn": {"type": "array", "items": {"type": "string"}},
        "must_include_formulas_cn": {"type": "array", "items": {"type": "string"}},
        "transition_cn": {"type": "string", "description": "How this chapter connects to the next chapter."},
    }
    derivation_properties = {
        "step_title_cn": {"type": "string"},
        "starting_assumption_cn": {"type": "string"},
        "equation_goal_cn": {"type": "string"},
        "physical_meaning_cn": {"type": "string"},
        "next_connection_cn": {"type": "string"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "course_goal_cn": {"type": "string"},
            "audience_prerequisites_cn": {"type": "array", "items": {"type": "string"}},
            "chapter_outline": {
                "type": "array",
                "minItems": 6,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": chapter_properties,
                    "required": list(chapter_properties),
                },
            },
            "derivation_ladder": {
                "type": "array",
                "minItems": 8,
                "maxItems": 14,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": derivation_properties,
                    "required": list(derivation_properties),
                },
            },
            "figure_reading_plan_cn": {"type": "array", "items": {"type": "string"}},
            "model_fitting_plan_cn": {"type": "array", "items": {"type": "string"}},
            "depth_guardrails_cn": {
                "type": "string",
                "description": "Rules that keep the final lesson systematic, foundational, and complete.",
            },
        },
        "required": [
            "course_goal_cn",
            "audience_prerequisites_cn",
            "chapter_outline",
            "derivation_ladder",
            "figure_reading_plan_cn",
            "model_fitting_plan_cn",
            "depth_guardrails_cn",
        ],
    }


def _weekend_lesson_section_schema(fields: list[str]) -> dict[str, Any]:
    descriptions = {
        "detailed_explanation_cn": "至少 5 段，系统讲科学问题、历史动机、方法、关键结果、局限和后续影响。",
        "background_cn": "至少 5 段，从历史背景、核心问题、为什么重要、常见误区讲起。",
        "basic_theory_cn": "至少 5–8 段，从基础物理图像逐步引入关键量、模型假设和观测/分析逻辑。",
        "formula_derivation_cn": "8–14 个 LaTeX 公式组成的连续推导链，每一步解释假设、符号、物理含义和与可观测量的连接。",
        "model_fitting_cn": "至少 5 段，讲拟合模型、参数、似然/后验、残差诊断、系统误差和应用。",
        "key_sections_cn": "用课程方式说明经典论文或经典结果的重点段落应该怎么读。",
        "figures_to_check_cn": "列出 5–8 类关键图表或诊断量，并说明图上应该看什么。",
        "key_figure_analysis_cn": "至少 5 个逐图导读条目，说明坐标轴、模型线、数据点、残差、结论和误读风险。",
        "followup_reading_cn": "至少 3 段，说明从这项经典工作读到现代研究的路径。",
        "next_lesson_suggestions_cn": "给出同一系列下一讲最自然的 1-3 个方向，并说明与本讲边界的关系。",
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {field: {"type": "string", "description": descriptions.get(field, "课程章节正文。")} for field in fields},
        "required": fields,
    }


def _figure_selection_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "selections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "fig_id": {"type": "string"},
                        "relevance_score": {"type": "integer", "minimum": 1, "maximum": 10},
                        "related_section_cn": {"type": "string", "description": "这张图对应日报中的哪个图表建议、逐图导读或模型拟合段落。"},
                        "reason_cn": {"type": "string", "description": "为什么这张图比其他候选图更值得嵌入。"},
                    },
                    "required": ["fig_id", "relevance_score", "related_section_cn", "reason_cn"],
                },
            }
        },
        "required": ["selections"],
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
                        "detailed_explanation_cn": {"type": "string", "description": "至少 4 段，按科学问题、作者怎么做、关键结果、局限和下一步详细讲解整篇文章。"},
                        "background_cn": {"type": "string", "description": "至少 4 段，解释研究对象、历史问题、观测/理论背景、为什么现在值得重新看，以及该领域常见误区。"},
                        "basic_theory_cn": {"type": "string", "description": "至少 4 段，从基础物理图像讲到本文模型假设、关键量、观测方法或仪器/数据分析逻辑。"},
                        "formula_derivation_cn": {"type": "string", "description": "包含 6–12 个 LaTeX 公式，按推导阶梯解释每个符号和步骤，从基础假设连接到论文核心方程、可观测量或统计诊断。"},
                        "model_fitting_cn": {"type": "string", "description": "至少 4 段，说明模型拟合、参数估计、似然/后验、系统误差、退化关系和实际应用。"},
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
