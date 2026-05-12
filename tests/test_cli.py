from astro_daily.cli import main
from astro_daily.pipeline import DEFERRED_RETRY_EXIT_CODE, DeferredRetryNeeded


def test_run_returns_deferred_retry_exit_code(monkeypatch):
    def fake_run_pipeline(**_kwargs):
        raise DeferredRetryNeeded("primary arXiv has zero papers for the run date")

    monkeypatch.setattr("astro_daily.cli.run_pipeline", fake_run_pipeline)

    assert main(["run", "--defer-if-unfresh"]) == DEFERRED_RETRY_EXIT_CODE
