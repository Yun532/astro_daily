from __future__ import annotations

import json
import os

import requests
from dotenv import load_dotenv


def send_wecom_markdown(content: str, dry_run: bool = False) -> None:
    load_dotenv()
    webhook_url = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("WECOM_WEBHOOK_URL is required for WeCom bot push")

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": content,
        },
    }
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    response = requests.post(webhook_url, json=payload, timeout=20)
    data = response.json()
    print(json.dumps(data, ensure_ascii=False))
    if data.get("errcode") != 0:
        raise RuntimeError("WeCom bot markdown message failed")
