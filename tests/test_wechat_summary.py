from astro_daily.models import Paper, PaperScore, PaperSummary, ScoredPaper
from src.wechat_summary import compress_for_wechat, select_wechat_papers, wechat_category_counts


def scored(paper_id: str, category: str, final_score: float) -> ScoredPaper:
    return ScoredPaper(
        paper=Paper(
            paper_id=paper_id,
            title=f"Paper {paper_id}",
            url=f"https://example.com/{paper_id}",
            source="arXiv",
            category=category,
        ),
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=final_score, keep=True, reason="important"),
        summary=PaperSummary(
            paper_id=paper_id,
            title_cn=f"论文 {paper_id}",
            summary_cn="这篇论文给出了新的观测或理论结果，能够帮助读者理解相关天体物理过程和后续观测方向。",
            why_important_cn="它在今天的候选论文中评分较高，并且与高能天体物理问题直接相关。",
            value_cn="有观测和理论价值。",
            why_care_cn="值得继续关注。",
        ),
    )


def test_compress_for_wechat_is_markdown_and_short():
    papers = [scored(str(index), "astro-ph.HE", 9.5 - index * 0.1) for index in range(6)]
    text = compress_for_wechat(papers, "2026-05-02", "report.html")
    assert "# 天文日报｜2026-05-02" in text
    assert "[完整报告](report.html)" in text
    assert "1. **Paper 0**" in text
    assert "[阅读全文](https://example.com/0)" in text
    assert len(text.encode("utf-8")) <= 3800


def test_compress_for_wechat_enforces_byte_limit():
    papers = [scored(str(index), "astro-ph.HE", 9.5 - index * 0.1) for index in range(6)]
    for item in papers:
        item.summary.summary_cn = "这是一段很长的中文摘要。" * 120
        item.summary.why_important_cn = "这是一段很长的重要性说明。" * 80
    text = compress_for_wechat(papers, "2026-05-02", "https://example.com/reports/2026-05-02.html")
    assert len(text.encode("utf-8")) <= 3800
    assert "[完整报告](https://example.com/reports/2026-05-02.html)" in text


def test_non_he_needs_high_score_for_wechat_selection():
    papers = [
        scored("he", "astro-ph.HE", 7.0),
        scored("co-low", "astro-ph.CO", 7.9),
        scored("im-high", "astro-ph.IM", 8.7),
    ]
    selected = select_wechat_papers(papers)
    ids = [item.paper.paper_id for item in selected]
    assert "co-low" not in ids
    assert "he" in ids
    assert "im-high" in ids
    assert wechat_category_counts(selected) == (1, 1, 0)


def test_supplemental_wechat_message_uses_non_daily_wording():
    papers = [scored(str(index), "astro-ph.HE", 7.0) for index in range(3)]

    text = compress_for_wechat(papers, "2026-05-08", "report.html", supplemental=True)

    assert "补充推荐：3 篇" in text
    assert "不是今日每日论文" in text
    assert "今日精选" not in text
    assert "类型：补充推荐（非今日每日论文）" in text


def test_supplemental_wechat_selection_preserves_pipeline_choices():
    papers = [
        scored("co-low", "astro-ph.CO", 7.1),
        scored("ga-low", "astro-ph.GA", 7.0),
        scored("he", "astro-ph.HE", 6.5),
        scored("extra", "astro-ph.HE", 9.0),
    ]

    selected = select_wechat_papers(papers, supplemental=True)

    assert [item.paper.paper_id for item in selected] == ["co-low", "ga-low", "he"]
