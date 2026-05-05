from __future__ import annotations

import json
import logging
import re

from astro_daily.config import Settings
from src.clawbot_client import load_cached_context_token, load_clawbot_account, send_clawbot_text

MAX_CLAWBOT_TEXT_CHARS = 1800

logger = logging.getLogger(__name__)


def send_clawbot_report_message(settings: Settings, content: str, dry_run: bool = False) -> None:
    recipient = (settings.clawbot.default_recipient or "").strip()
    if not recipient:
        raise RuntimeError("clawbot.default_recipient is required for ClawBot push")
    text = _plain_text(content)
    if len(text) > MAX_CLAWBOT_TEXT_CHARS:
        text = text[: MAX_CLAWBOT_TEXT_CHARS - 1].rstrip() + "…"
    payload = {"to_user_id": recipient, "text": text}
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    account = load_clawbot_account(settings)
    context_token = load_cached_context_token(recipient)
    try:
        send_clawbot_text(account, recipient, text, context_token=context_token)
    except RuntimeError:
        if not context_token:
            raise
        logger.warning("ClawBot send with cached context token failed; retrying without context token")
        send_clawbot_text(account, recipient, text, context_token=None)


def _plain_text(content: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1：\2", content)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "")
    return text.strip()
