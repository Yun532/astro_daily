from datetime import date
from pathlib import Path

from PIL import Image

from astro_daily.config import Settings
from astro_daily.models import FigureSelection, Paper, PaperScore, PaperSummary, ScoredPaper
from src.figure_extractor import attach_extracted_figures


class FakeProvenance:
    def __init__(self, composite_strategy: str | None = None):
        self.source_type = "arxiv_source"
        self.locator = "fixture"
        self.details = {"composite_strategy": composite_strategy} if composite_strategy else {}


class FakePanel:
    def __init__(self, label: str, output_file: str):
        self.label = label
        self.output_file = output_file
        self.source_image = None
        self.verified = True


class FakeRecord:
    def __init__(
        self,
        fig_id: str = "Fig01",
        caption: str = "A verified figure caption.",
        panels: list[FakePanel] | None = None,
        composite_strategy: str | None = None,
    ):
        self.fig_id = fig_id
        self.output_file = f"figures/{fig_id}.png"
        self.caption = caption
        self.confidence = "high"
        self.source_type = "arxiv_source"
        self.provenance = [FakeProvenance(composite_strategy)] if composite_strategy else []
        self.panels = panels or []


class FakeResult:
    def __init__(self, output_dir: Path, figures: list[FakeRecord] | None = None):
        self.output_dir = str(output_dir)
        self.figures = figures or [FakeRecord()]


def make_settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
            "scoring": {},
            "llm": {},
            "report": {},
            "wechat": {"enabled": False},
            "figure_extraction": {
                "enabled": True,
                "cache_dir": "figure_cache",
                "asset_dir": "docs/assets/figures",
                "max_figures_per_paper": 1,
            },
            "root_dir": tmp_path,
        }
    )


def test_attach_extracted_figures_copies_verified_assets(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    paper = Paper(paper_id="2605.00001", title="Paper", url="https://arxiv.org/abs/2605.00001", source="arXiv")
    scored = ScoredPaper(
        paper=paper,
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="ok"),
        summary=PaperSummary(paper_id="2605.00001", title_cn="标题", summary_cn="总结", why_important_cn="重要", value_cn="价值", why_care_cn="关注"),
    )
    outdir = tmp_path / "paperfig-out"
    (outdir / "figures").mkdir(parents=True)
    (outdir / "figures" / "Fig01.png").write_bytes(b"png")

    monkeypatch.setattr("src.figure_extractor._run_paperfig", lambda _input, _settings: FakeResult(outdir))

    result = attach_extracted_figures([scored], settings, run_date=date(2026, 5, 5))

    assert result.attempted == 1
    assert result.extracted == 1
    assert scored.summary.extracted_figures[0].fig_id == "Fig01"
    assert scored.summary.extracted_figures[0].image_url == "../assets/figures/2026-05-05/2605.00001/Fig01.png"
    assert (tmp_path / "docs" / "assets" / "figures" / "2026-05-05" / "2605.00001" / "Fig01.png").exists()


def test_attach_extracted_figures_uses_llm_selection(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.figure_extraction.max_figures_per_paper = 2
    paper = Paper(paper_id="2605.00001", title="Paper", url="https://arxiv.org/abs/2605.00001", source="arXiv")
    scored = ScoredPaper(
        paper=paper,
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="ok"),
        summary=PaperSummary(
            paper_id="2605.00001",
            title_cn="标题",
            summary_cn="总结",
            why_important_cn="重要",
            value_cn="价值",
            why_care_cn="关注",
            figures_to_check_cn="重点看 Fig03 的残差和 Fig02 的谱线。",
            key_figure_analysis_cn="Fig03 给出关键残差，Fig02 给出能谱结构。",
        ),
    )
    outdir = tmp_path / "paperfig-out"
    (outdir / "figures").mkdir(parents=True)
    for fig_id in ["Fig01", "Fig02", "Fig03"]:
        (outdir / "figures" / f"{fig_id}.png").write_bytes(b"png")

    monkeypatch.setattr(
        "src.figure_extractor._run_paperfig",
        lambda _input, _settings: FakeResult(
            outdir,
            [
                FakeRecord("Fig01", "Overview plot."),
                FakeRecord("Fig02", "Spectral structure."),
                FakeRecord("Fig03", "Residual diagnostics."),
            ],
        ),
    )

    class FakeAnalyst:
        def select_figures_for_paper(self, **_kwargs):
            return [
                FigureSelection(fig_id="Fig03", relevance_score=10, related_section_cn="关键图表逐图导读", reason_cn="残差图对应逐图导读。"),
                FigureSelection(fig_id="Fig02", relevance_score=9, related_section_cn="建议重点查看的图表", reason_cn="能谱结构对应图表建议。"),
            ]

    result = attach_extracted_figures([scored], settings, run_date=date(2026, 5, 5), analyst=FakeAnalyst())

    assert result.extracted == 2
    assert [figure.fig_id for figure in scored.summary.extracted_figures] == ["Fig03", "Fig02"]
    assert scored.summary.extracted_figures[0].selection_reason_cn == "残差图对应逐图导读。"


def test_attach_extracted_figures_is_nonfatal(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    paper = Paper(paper_id="2605.00001", title="Paper", url="https://arxiv.org/abs/2605.00001", source="arXiv")
    scored = ScoredPaper(
        paper=paper,
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="ok"),
        summary=PaperSummary(paper_id="2605.00001", title_cn="标题", summary_cn="总结", why_important_cn="重要", value_cn="价值", why_care_cn="关注"),
    )
    monkeypatch.setattr("src.figure_extractor._run_paperfig", lambda _input, _settings: (_ for _ in ()).throw(RuntimeError("boom")))

    result = attach_extracted_figures([scored], settings, run_date=date(2026, 5, 5))

    assert result.failed == 1
    assert scored.summary.extracted_figures == []


def test_attach_extracted_figures_reflows_vertical_panel_composites(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    settings.figure_extraction.max_figures_per_paper = 1
    settings.figure_extraction.panel_grid_max_width_px = 1200
    paper = Paper(paper_id="2605.00001", title="Paper", url="https://arxiv.org/abs/2605.00001", source="arXiv")
    scored = ScoredPaper(
        paper=paper,
        score=PaperScore(novelty_score=8, importance_score=8, relevance_to_me=8, final_score=8, keep=True, reason="ok"),
        summary=PaperSummary(paper_id="2605.00001", title_cn="title", summary_cn="summary", why_important_cn="important", value_cn="value", why_care_cn="care"),
    )
    outdir = tmp_path / "paperfig-out"
    figures_dir = outdir / "figures"
    figures_dir.mkdir(parents=True)
    Image.new("RGB", (200, 900), "white").save(figures_dir / "Fig01.png")
    for index, color in enumerate(["red", "green", "blue", "yellow"], start=1):
        label = chr(ord("a") + index - 1)
        Image.new("RGB", (400, 300), color).save(figures_dir / f"Fig01_panel_{label}.png")

    panels = [FakePanel(label, f"figures/Fig01_panel_{label}.png") for label in ["a", "b", "c", "d"]]
    monkeypatch.setattr("src.figure_extractor._run_paperfig", lambda _input, _settings: FakeResult(outdir, [FakeRecord("Fig01", panels=panels, composite_strategy="source_order_vertical_stack")]))

    result = attach_extracted_figures([scored], settings, run_date=date(2026, 5, 5))

    assert result.extracted == 1
    target = tmp_path / "docs" / "assets" / "figures" / "2026-05-05" / "2605.00001" / "Fig01.png"
    with Image.open(target) as image:
        assert image.width == 824
        assert image.height == 624
        assert image.height < 900
