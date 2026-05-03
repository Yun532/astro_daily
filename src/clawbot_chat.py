from __future__ import annotations

import logging
import time
from typing import Any

import anthropic

from astro_daily.config import Settings
from src.clawbot_client import ClawBotMessage, load_clawbot_account, poll_clawbot_once, send_clawbot_text
from src.report_urls import latest_report_url

logger = logging.getLogger(__name__)

MAX_CLAWBOT_REPLY_CHARS = 1800
CHAT_SYSTEM_PROMPT = """你是通过个人微信与用户对话的 Astro Daily 助手。
用中文直接回答用户输入。回答要简洁、准确；如果用户问到本项目或当天日报，可以说明你能帮他查询、发送或解释 Astro Daily 内容。"""


class ClawBotChatResponder:
    def __init__(self, settings: Settings):
        settings.require_llm_key()
        self.settings = settings
        client_kwargs: dict[str, Any] = {"api_key": settings.anthropic_api_key}
        if settings.llm.base_url:
            client_kwargs["base_url"] = settings.llm.base_url
        self.client = anthropic.Anthropic(**client_kwargs)

    def answer(self, prompt: str) -> str:
        request: dict[str, Any] = {
            "model": self.settings.llm.model,
            "max_tokens": min(self.settings.llm.max_tokens, 2000),
            "system": _chat_system_prompt(self.settings),
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.settings.llm.use_claude_native_features:
            request["thinking"] = {"type": "adaptive"}
            request["output_config"] = {"effort": self.settings.llm.effort}
        try:
            response = self.client.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise RuntimeError("Anthropic authentication failed; check ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError("Anthropic API rate limit reached; retry later") from exc
        except anthropic.APIStatusError as exc:
            request_id = getattr(exc, "request_id", None)
            raise RuntimeError(f"Anthropic API error {exc.status_code}; request_id={request_id}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError("Could not connect to Anthropic API") from exc

        text = "\n".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise RuntimeError("LLM returned no text block")
        return _truncate_reply(text)


def run_clawbot_chat_once(settings: Settings, *, dry_run: bool = False) -> int:
    messages = poll_clawbot_once(settings)
    if not messages:
        print("Received 0 ClawBot messages")
        return 0

    responder = ClawBotChatResponder(settings)
    account = load_clawbot_account(settings)
    replied = 0
    print(f"Received {len(messages)} ClawBot messages")
    for message in messages:
        if reply_to_clawbot_message(settings, account, responder, message, dry_run=dry_run):
            replied += 1
    return replied


def run_clawbot_chat_loop(settings: Settings, *, poll_interval: float = 2.0, dry_run: bool = False) -> None:
    responder = ClawBotChatResponder(settings)
    account = load_clawbot_account(settings)
    print("ClawBot chat listener started")
    while True:
        messages = poll_clawbot_once(settings)
        for message in messages:
            reply_to_clawbot_message(settings, account, responder, message, dry_run=dry_run)
        time.sleep(poll_interval)


def reply_to_clawbot_message(
    settings: Settings,
    account: Any,
    responder: ClawBotChatResponder,
    message: ClawBotMessage,
    *,
    dry_run: bool = False,
) -> bool:
    prompt = message.text.strip()
    if not prompt:
        return False
    token_state = "context_token=yes" if message.context_token else "context_token=no"
    print(f"- {message.sender_id} ({token_state}): {prompt}")
    reply = responder.answer(prompt)
    if dry_run:
        print(f"Dry-run reply to {message.sender_id}: {reply}")
    else:
        send_clawbot_text(account, message.sender_id, reply, context_token=message.context_token)
        print(f"Replied to {message.sender_id}")
    logger.info("Replied to ClawBot message from %s", message.sender_id)
    return True


def _chat_system_prompt(settings: Settings) -> str:
    return "\n".join(
        [
            CHAT_SYSTEM_PROMPT,
            f"当前最新完整报告链接：{latest_report_url(settings)}",
            "如果用户询问网页、报告或链接，优先原样发送上面的最新完整报告链接，不要自己编造 URL。",
        ]
    )


def _truncate_reply(text: str) -> str:
    if len(text) <= MAX_CLAWBOT_REPLY_CHARS:
        return text
    return text[: MAX_CLAWBOT_REPLY_CHARS - 1].rstrip() + "…"
