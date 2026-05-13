from datetime import date

import pytest

from astro_daily.feedback import append_feedback, feedback_context_for_scoring, load_feedback
from astro_daily.cli import main


def test_append_and_load_feedback(tmp_path):
    path = tmp_path / "feedback.jsonl"

    append_feedback(
        path,
        paper_id="2605.11894",
        rating="love",
        reason="cluster neutrino gamma-ray connection",
        feedback_date=date(2026, 5, 13),
    )

    records = load_feedback(path)
    assert len(records) == 1
    assert records[0].paper_id == "2605.11894"
    assert records[0].rating == "love"
    assert records[0].date == date(2026, 5, 13)


def test_feedback_context_summarizes_recent_preferences(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_feedback(path, paper_id="a", rating="love", reason="cluster neutrino gamma-ray", feedback_date=date(2026, 5, 13))
    append_feedback(path, paper_id="b", rating="skip", reason="too cosmology-heavy", feedback_date=date(2026, 5, 13))

    context = feedback_context_for_scoring(load_feedback(path))

    assert context["positive_paper_ids"] == ["a"]
    assert context["negative_paper_ids"] == ["b"]
    assert "neutrino" in context["positive_terms"]
    assert "cosmology-heavy" in context["negative_terms"]


def test_append_feedback_rejects_unknown_rating(tmp_path):
    with pytest.raises(ValueError, match="rating"):
        append_feedback(tmp_path / "feedback.jsonl", paper_id="2605.1", rating="maybe")


def test_feedback_cli_writes_configured_feedback_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  arxiv:
    primary:
      - category: astro-ph.HE
        max_results: 1
  rss:
    feeds: []
scoring: {}
llm: {}
report:
  feedback_file: prefs.jsonl
wechat:
  enabled: false
""".strip(),
        encoding="utf-8",
    )

    exit_code = main(["feedback", "--config", str(config_path), "useful", "2605.11894", "--reason", "cta synergy"])

    assert exit_code == 0
    records = load_feedback(tmp_path / "prefs.jsonl")
    assert records[0].rating == "useful"
    assert records[0].reason == "cta synergy"


def test_notify_update_cli_sends_enabled_channels(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  arxiv:
    primary:
      - category: astro-ph.HE
        max_results: 1
  rss:
    feeds: []
scoring: {}
llm: {}
report: {}
wechat:
  enabled: true
clawbot:
  enabled: true
  default_recipient: user@im.wechat
""".strip(),
        encoding="utf-8",
    )
    sent = []
    monkeypatch.setattr("astro_daily.cli.send_wecom_markdown", lambda content, dry_run=False: sent.append(("wecom", content, dry_run)))
    monkeypatch.setattr("astro_daily.cli.send_clawbot_report_message", lambda settings, content, dry_run=False: sent.append(("clawbot", content, dry_run)))

    exit_code = main(["notify-update", "--config", str(config_path), "--title", "Backup", "--text", "Saved changes", "--dry-run"])

    assert exit_code == 0
    assert [item[0] for item in sent] == ["wecom", "clawbot"]
    assert sent[0][1] == "**Backup**\n\nSaved changes"
    assert sent[0][2] is True


def test_notify_update_cli_continues_when_one_channel_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  arxiv:
    primary:
      - category: astro-ph.HE
        max_results: 1
  rss:
    feeds: []
scoring: {}
llm: {}
report: {}
wechat:
  enabled: true
clawbot:
  enabled: true
  default_recipient:
""".strip(),
        encoding="utf-8",
    )
    sent = []
    monkeypatch.setattr("astro_daily.cli.send_wecom_markdown", lambda content, dry_run=False: sent.append(("wecom", content, dry_run)))
    monkeypatch.setattr(
        "astro_daily.cli.send_clawbot_report_message",
        lambda settings, content, dry_run=False: (_ for _ in ()).throw(RuntimeError("missing recipient")),
    )

    exit_code = main(["notify-update", "--config", str(config_path), "--text", "Saved changes", "--dry-run"])

    assert exit_code == 0
    assert [item[0] for item in sent] == ["wecom"]
