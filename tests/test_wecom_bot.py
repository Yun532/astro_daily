import json

from src.push_wecom_bot import send_wecom_markdown


def test_send_wecom_markdown_dry_run_prints_payload(monkeypatch, capsys):
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/webhook")
    send_wecom_markdown("# hello", dry_run=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"msgtype": "markdown", "markdown": {"content": "# hello"}}


def test_send_wecom_markdown_raises_on_api_error(monkeypatch):
    class Response:
        def json(self):
            return {"errcode": 1, "errmsg": "bad"}

    def post(url, json, timeout):
        return Response()

    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setattr("src.push_wecom_bot.requests.post", post)
    try:
        send_wecom_markdown("# hello")
    except RuntimeError as exc:
        assert "WeCom bot" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
