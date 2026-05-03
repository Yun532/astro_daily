from astro_daily.config import LlmConfig, load_settings


def test_env_overrides_for_local_proxy(tmp_path, monkeypatch):
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
llm:
  model: claude-opus-4-7
report: {}
wechat:
  enabled: false
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "gpt-5.5")
    monkeypatch.setenv("ANTHROPIC_API_MODE", "compatible")

    settings = load_settings(config_path)

    assert settings.anthropic_api_key == "token"
    assert settings.llm.base_url == "http://127.0.0.1:8317"
    assert settings.llm.model == "gpt-5.5"
    assert settings.llm.api_mode == "compatible"
    assert not settings.llm.use_claude_native_features
    assert settings.site_base_url == "本地HTML报告"
    assert not settings.publish.enabled


def test_publish_config_parses_enabled_block(tmp_path, monkeypatch):
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
  enabled: false
site_base_url: https://example.github.io/astro-daily
publish:
  enabled: true
  provider: github_pages
  mode: git_push
  repo_url: https://github.com/example/astro-daily.git
  branch: main
  docs_dir: docs
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_MODE", raising=False)

    settings = load_settings(config_path)

    assert settings.publish.enabled
    assert settings.publish.repo_url == "https://github.com/example/astro-daily.git"
    assert settings.site_base_url == "https://example.github.io/astro-daily"
    assert settings.scoring.max_candidates == 120
    assert settings.scoring.max_papers_per_report == 15
    assert settings.scoring.same_day_target == 5
    assert settings.scoring.max_backfill_papers == 5
    assert settings.scoring.non_he_min_relevance == 6
    assert not settings.clawbot.enabled


    assert not LlmConfig(model="gpt-5.5").use_claude_native_features
    assert LlmConfig(model="claude-opus-4-7").use_claude_native_features


def test_clawbot_config_parses_enabled_block(tmp_path, monkeypatch):
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
  enabled: false
clawbot:
  enabled: true
  default_recipient: user@im.wechat
  send_report: true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_MODE", raising=False)

    settings = load_settings(config_path)

    assert settings.clawbot.enabled
    assert settings.clawbot.default_recipient == "user@im.wechat"
    assert settings.clawbot.send_report
