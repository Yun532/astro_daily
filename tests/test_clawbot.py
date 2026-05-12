import json

import pytest
import requests

from astro_daily.config import Settings
from src.clawbot_chat import ClawBotChatResponder, reply_to_clawbot_message, run_clawbot_chat_loop
from src.clawbot_client import ClawBotAccount, ClawBotMessage, get_clawbot_updates, send_clawbot_text
from src.push_clawbot import send_clawbot_report_message


def test_send_clawbot_text_posts_expected_payload(monkeypatch):
    calls = []

    class Response:
        ok = True
        text = "{}"

        def json(self):
            return {"ret": 0}

    def post(url, data, headers, timeout):
        calls.append((url, json.loads(data.decode("utf-8")), headers, timeout))
        return Response()

    monkeypatch.setattr("src.clawbot_client.requests.post", post)
    account = ClawBotAccount(token="token", base_url="https://example.com")

    client_id = send_clawbot_text(account, "user@im.wechat", "hello", context_token="ctx")

    url, payload, headers, timeout = calls[0]
    assert url == "https://example.com/ilink/bot/sendmessage"
    assert payload["msg"]["to_user_id"] == "user@im.wechat"
    assert payload["msg"]["message_type"] == 2
    assert payload["msg"]["message_state"] == 2
    assert payload["msg"]["item_list"] == [{"type": 1, "text_item": {"text": "hello"}}]
    assert payload["msg"]["context_token"] == "ctx"
    assert headers["Authorization"] == "Bearer token"
    assert client_id.startswith("astro-daily:")


def test_get_clawbot_updates_extracts_text_and_sync(monkeypatch):
    class Response:
        ok = True
        text = "{}"

        def json(self):
            return {
                "ret": 0,
                "get_updates_buf": "next",
                "msgs": [
                    {
                        "message_type": 1,
                        "from_user_id": "user@im.wechat",
                        "context_token": "ctx",
                        "item_list": [{"type": 1, "text_item": {"text": "ping"}}],
                    }
                ],
            }

    def post(url, data, headers, timeout):
        return Response()

    monkeypatch.setattr("src.clawbot_client.requests.post", post)
    account = ClawBotAccount(token="token", base_url="https://example.com")

    messages, sync_buf = get_clawbot_updates(account, "old")

    assert sync_buf == "next"
    assert len(messages) == 1
    assert messages[0].sender_id == "user@im.wechat"
    assert messages[0].text == "ping"
    assert messages[0].context_token == "ctx"


def test_send_clawbot_report_message_dry_run_prints_payload(capsys):
    settings = Settings.model_validate(
        {
            "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
            "scoring": {},
            "llm": {},
            "report": {},
            "wechat": {"enabled": False},
            "clawbot": {"default_recipient": "user@im.wechat"},
        }
    )

    send_clawbot_report_message(settings, "[完整报告](https://example.com/report.html)", dry_run=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"to_user_id": "user@im.wechat", "text": "完整报告：https://example.com/report.html"}


def test_send_clawbot_report_message_retries_without_stale_context(monkeypatch):
    settings = Settings.model_validate(
        {
            "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
            "scoring": {},
            "llm": {},
            "report": {},
            "wechat": {"enabled": False},
            "clawbot": {"default_recipient": "user@im.wechat"},
        }
    )
    account = ClawBotAccount(token="token", base_url="https://example.com")
    calls = []

    def send(_account, to_user_id, text, context_token=None):
        calls.append((_account, to_user_id, text, context_token))
        if context_token == "stale-context":
            raise RuntimeError("ClawBot API error")

    monkeypatch.setattr("src.push_clawbot.load_clawbot_account", lambda _settings: account)
    monkeypatch.setattr("src.push_clawbot.load_cached_context_token", lambda _recipient: "stale-context")
    monkeypatch.setattr("src.push_clawbot.send_clawbot_text", send)

    send_clawbot_report_message(settings, "日报内容", dry_run=False)

    assert calls == [
        (account, "user@im.wechat", "日报内容", "stale-context"),
        (account, "user@im.wechat", "日报内容", None),
    ]


def test_clawbot_chat_responder_uses_compatible_request(monkeypatch):
    calls = []

    class Block:
        type = "text"
        text = "你好，我收到了。"

    class Response:
        content = [Block()]

    class Messages:
        def create(self, **request):
            calls.append(request)
            return Response()

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.messages = Messages()

    monkeypatch.setattr("src.clawbot_chat.anthropic.Anthropic", Client)
    settings = Settings.model_validate(
        {
            "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
            "scoring": {},
            "llm": {"model": "gpt-5.5", "base_url": "http://127.0.0.1:8317", "api_mode": "compatible"},
            "report": {},
            "wechat": {"enabled": False},
            "anthropic_api_key": "token",
        }
    )

    reply = ClawBotChatResponder(settings).answer("你能收到吗")

    assert reply == "你好，我收到了。"
    assert calls[0] == {"api_key": "token", "base_url": "http://127.0.0.1:8317"}
    assert calls[1]["model"] == "gpt-5.5"
    assert calls[1]["messages"] == [{"role": "user", "content": "你能收到吗"}]
    assert "thinking" not in calls[1]
    assert "output_config" not in calls[1]


def test_clawbot_chat_loop_retries_transient_poll_errors(monkeypatch, caplog):
    sleeps = []

    class Responder:
        def __init__(self, _settings):
            pass

    def sleep(seconds):
        sleeps.append(seconds)
        raise KeyboardInterrupt

    settings = Settings.model_validate(
        {
            "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
            "scoring": {},
            "llm": {},
            "report": {},
            "wechat": {"enabled": False},
        }
    )
    monkeypatch.setattr("src.clawbot_chat.ClawBotChatResponder", Responder)
    monkeypatch.setattr("src.clawbot_chat.load_clawbot_account", lambda _settings: ClawBotAccount(token="token", base_url="https://example.com"))
    monkeypatch.setattr("src.clawbot_chat.poll_clawbot_once", lambda _settings: (_ for _ in ()).throw(requests.exceptions.SSLError("temporary eof")))
    monkeypatch.setattr("src.clawbot_chat.time.sleep", sleep)

    with pytest.raises(KeyboardInterrupt):
        run_clawbot_chat_loop(settings, poll_interval=0.1)

    assert sleeps == [0.1]
    assert "ClawBot polling failed; will retry" in caplog.text


def test_reply_to_clawbot_message_sends_answer_with_context(monkeypatch):
    sends = []

    class Responder:
        def answer(self, prompt):
            assert prompt == "有吗"
            return "有，我收到了。"

    def send(account, to_user_id, text, context_token=None):
        sends.append((account, to_user_id, text, context_token))

    monkeypatch.setattr("src.clawbot_chat.send_clawbot_text", send)
    settings = Settings.model_validate(
        {
            "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
            "scoring": {},
            "llm": {},
            "report": {},
            "wechat": {"enabled": False},
        }
    )
    account = ClawBotAccount(token="token", base_url="https://example.com")
    message = ClawBotMessage(sender_id="user@im.wechat", text="有吗", context_token="ctx")

    assert reply_to_clawbot_message(settings, account, Responder(), message)

    assert sends == [(account, "user@im.wechat", "有，我收到了。", "ctx")]
