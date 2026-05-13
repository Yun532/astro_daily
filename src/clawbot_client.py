from __future__ import annotations

import base64
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from astro_daily.config import Settings

logger = logging.getLogger(__name__)

CHANNEL_VERSION = "0.1.0"
MSG_TYPE_USER = 1
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2
MSG_ITEM_TEXT = 1
MSG_ITEM_VOICE = 3


@dataclass(frozen=True)
class ClawBotAccount:
    token: str
    base_url: str
    account_id: str | None = None
    user_id: str | None = None


@dataclass(frozen=True)
class ClawBotMessage:
    sender_id: str
    text: str
    context_token: str | None = None


def default_credentials_file() -> Path:
    return Path.home() / ".claude" / "channels" / "wechat" / "account.json"


def default_sync_file() -> Path:
    return Path.home() / ".claude" / "channels" / "wechat" / "sync_buf.txt"


def default_context_tokens_file() -> Path:
    return Path.home() / ".claude" / "channels" / "wechat" / "context_tokens.json"


def load_clawbot_account(settings: Settings) -> ClawBotAccount:
    path = Path(settings.clawbot.credentials_file) if settings.clawbot.credentials_file else default_credentials_file()
    if not path.exists():
        raise RuntimeError(f"ClawBot credentials file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    token = str(data.get("token") or "").strip()
    if not token:
        raise RuntimeError("ClawBot credentials file does not contain token")
    return ClawBotAccount(
        token=token,
        base_url=str(data.get("baseUrl") or settings.clawbot.base_url).strip().rstrip("/"),
        account_id=data.get("accountId"),
        user_id=data.get("userId"),
    )


def send_clawbot_text(
    account: ClawBotAccount,
    to_user_id: str,
    text: str,
    context_token: str | None = None,
    *,
    timeout: int = 15,
) -> str:
    client_id = f"astro-daily:{secrets.token_hex(8)}"
    payload: dict[str, Any] = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MSG_TYPE_BOT,
            "message_state": MSG_STATE_FINISH,
            "item_list": [{"type": MSG_ITEM_TEXT, "text_item": {"text": text}}],
        },
        "base_info": {"channel_version": CHANNEL_VERSION},
    }
    if context_token:
        payload["msg"]["context_token"] = context_token
    _post(account, "ilink/bot/sendmessage", payload, timeout=timeout)
    return client_id


def get_clawbot_updates(account: ClawBotAccount, sync_buf: str = "", *, timeout: int = 35) -> tuple[list[ClawBotMessage], str]:
    payload = {
        "get_updates_buf": sync_buf,
        "base_info": {"channel_version": CHANNEL_VERSION},
    }
    data = _post(account, "ilink/bot/getupdates", payload, timeout=timeout)
    messages: list[ClawBotMessage] = []
    raw_messages = data.get("msgs") or []
    if raw_messages:
        logger.info("ClawBot returned raw messages; count=%s", len(raw_messages))
    for index, raw in enumerate(raw_messages):
        message_type = raw.get("message_type")
        item_types = [item.get("type") for item in raw.get("item_list") or []]
        if message_type != MSG_TYPE_USER:
            logger.info("ClawBot raw message ignored; index=%s message_type=%s item_types=%s", index, message_type, item_types)
            continue
        text = _extract_text(raw)
        if not text:
            logger.info("ClawBot user message ignored because no text was extracted; index=%s item_types=%s", index, item_types)
            continue
        messages.append(
            ClawBotMessage(
                sender_id=str(raw.get("from_user_id") or "unknown"),
                text=text,
                context_token=raw.get("context_token"),
            )
        )
    if raw_messages:
        logger.info("ClawBot extracted user text messages; count=%s", len(messages))
    return messages, str(data.get("get_updates_buf") or sync_buf)


def poll_clawbot_once(settings: Settings) -> list[ClawBotMessage]:
    account = load_clawbot_account(settings)
    sync_path = Path(settings.clawbot.sync_file) if settings.clawbot.sync_file else default_sync_file()
    sync_buf = sync_path.read_text(encoding="utf-8") if sync_path.exists() else ""
    messages, next_sync_buf = get_clawbot_updates(account, sync_buf)
    if next_sync_buf != sync_buf:
        sync_path.parent.mkdir(parents=True, exist_ok=True)
        sync_path.write_text(next_sync_buf, encoding="utf-8")
    _save_context_tokens(messages)
    return messages


def load_cached_context_token(sender_id: str) -> str | None:
    path = default_context_tokens_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    token = data.get(sender_id)
    return str(token) if token else None


def _save_context_tokens(messages: list[ClawBotMessage]) -> None:
    updates = {message.sender_id: message.context_token for message in messages if message.context_token}
    if not updates:
        return
    path = default_context_tokens_file()
    data: dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _post(account: ClawBotAccount, endpoint: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    response = requests.post(
        urljoin(f"{account.base_url.rstrip('/')}/", endpoint),
        data=body.encode("utf-8"),
        headers=_headers(account.token, body),
        timeout=timeout,
    )
    text = response.text
    if not response.ok:
        raise RuntimeError(f"ClawBot API HTTP {response.status_code}: {text}")
    data = response.json()
    if ("ret" in data and data.get("ret") != 0) or ("errcode" in data and data.get("errcode") != 0):
        raise RuntimeError(f"ClawBot API error: {json.dumps(data, ensure_ascii=False)}")
    return data


def _headers(token: str, body: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Content-Length": str(len(body.encode("utf-8"))),
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode("utf-8")).decode("ascii"),
    }


def _extract_text(message: dict[str, Any]) -> str:
    for item in message.get("item_list") or []:
        if item.get("type") == MSG_ITEM_TEXT:
            text = ((item.get("text_item") or {}).get("text") or "").strip()
            ref = item.get("ref_msg") or {}
            title = ref.get("title")
            if text and title:
                return f"[引用: {title}]\n{text}"
            if text:
                return text
        if item.get("type") == MSG_ITEM_VOICE:
            text = ((item.get("voice_item") or {}).get("text") or "").strip()
            if text:
                return text
    return ""
