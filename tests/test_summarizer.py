from datetime import date
import threading

from astro_daily.models import Paper, PaperScore, PaperSummary, ScoredPaper
from astro_daily.summarizer import add_summaries


def make_scored(paper_id: str) -> ScoredPaper:
    return ScoredPaper(
        paper=Paper(
            paper_id=paper_id,
            title=f"Paper {paper_id}",
            url=f"https://example.com/{paper_id}",
            source="arXiv",
            category="astro-ph.HE",
        ),
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="important"),
    )


def make_summary(paper_id: str) -> PaperSummary:
    return PaperSummary(
        paper_id=paper_id,
        title_cn=f"标题 {paper_id}",
        summary_cn="总结",
        why_important_cn="重要",
        value_cn="价值",
        why_care_cn="关注",
    )


def test_add_summaries_generates_single_papers_in_parallel():
    scored = [make_scored("2605.10001"), make_scored("2605.10002")]
    barrier = threading.Barrier(2)
    passed_barrier = 0
    lock = threading.Lock()

    class FakeAnalyst:
        def summarize_papers(self, papers, **_kwargs):
            nonlocal passed_barrier
            assert len(papers) == 1
            barrier.wait(timeout=2)
            with lock:
                passed_barrier += 1
            return [make_summary(papers[0].paper_id)]

    result = add_summaries(scored, FakeAnalyst(), run_date=date(2026, 5, 13), parallel_workers=2)

    assert passed_barrier == 2
    assert [item.summary.paper_id for item in result if item.summary] == ["2605.10001", "2605.10002"]


def test_add_summaries_uses_fallback_for_one_failed_paper():
    scored = [make_scored("2605.10003")]

    class FakeAnalyst:
        def summarize_papers(self, *_args, **_kwargs):
            raise RuntimeError("summary json broke")

    result = add_summaries(scored, FakeAnalyst(), run_date=date(2026, 5, 13), parallel_workers=2)

    assert result[0].summary is not None
    assert "自动详细解读生成失败" in result[0].summary.summary_cn
