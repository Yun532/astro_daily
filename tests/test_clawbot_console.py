from astro_daily.config import Settings
from src.clawbot_chat import reply_to_clawbot_message
from src.clawbot_client import ClawBotAccount, ClawBotMessage
from src.clawbot_console import handle_console_command


def _settings(tmp_path=None):
    data = {
        "sources": {"arxiv": {"primary": [{"category": "astro-ph.HE", "max_results": 1}]}, "rss": {"feeds": []}},
        "scoring": {},
        "llm": {},
        "report": {"feedback_file": "feedback.jsonl"},
        "wechat": {"enabled": False},
    }
    if tmp_path is not None:
        data["root_dir"] = tmp_path
    return Settings.model_validate(data)


def test_clawbot_console_help_does_not_call_llm(monkeypatch):
    sends = []

    class Responder:
        def answer(self, prompt):
            raise AssertionError("console commands must not call the LLM")

    def send(account, to_user_id, text, context_token=None):
        sends.append((to_user_id, text, context_token))

    monkeypatch.setattr("src.clawbot_chat.send_clawbot_text", send)
    account = ClawBotAccount(token="token", base_url="https://example.com")
    message = ClawBotMessage(sender_id="user@im.wechat", text="帮助", context_token="ctx")

    assert reply_to_clawbot_message(_settings(), account, Responder(), message)

    assert len(sends) == 1
    assert sends[0][0] == "user@im.wechat"
    assert "微信控制台可用命令" in sends[0][1]
    assert sends[0][2] == "ctx"


def test_clawbot_console_records_feedback(tmp_path):
    settings = _settings(tmp_path)

    reply = handle_console_command(settings, "记录反馈 love 2605.12345 很感兴趣")

    assert reply == "反馈已记录：love 2605.12345"
    saved = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8")
    assert '"paper_id": "2605.12345"' in saved
    assert '"rating": "love"' in saved
    assert "很感兴趣" in saved


def test_clawbot_console_rejects_unknown_feedback_rating(tmp_path):
    settings = _settings(tmp_path)

    reply = handle_console_command(settings, "记录反馈 delete 2605.12345 不喜欢")

    assert reply == "反馈类型不支持：delete。可用：love/useful/skip/bad"
    assert not (tmp_path / "feedback.jsonl").exists()


def test_clawbot_console_log_output_is_sanitized(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "clawbot-chat-test.err.log").write_text(
        "Authorization: Bearer secret-token\nfrom fakeuser123@im.wechat\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)

    reply = handle_console_command(settings, "查看日志 5")

    assert "secret-token" not in reply
    assert "fakeuser123@im.wechat" not in reply
    assert "Bearer <redacted>" in reply
    assert "<wechat-user>" in reply
