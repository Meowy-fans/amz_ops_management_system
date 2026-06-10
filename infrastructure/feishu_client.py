"""Feishu (Lark) notification client.

Sends structured messages to Feishu group chats via webhook.
Supports P0/P1/P2 severity levels and multiple message types.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ── severity & message types ────────────────────────────────────────

SEVERITY_COLORS = {
    "P0": "red",
    "P1": "orange",
    "P2": "blue",
}

SEVERITY_LABELS = {
    "P0": "🔴 紧急",
    "P1": "🟡 注意",
    "P2": "🔵 信息",
}


@dataclass
class FeishuMessage:
    title: str
    content: str = ""
    severity: str = "P2"
    tags: List[str] = field(default_factory=list)
    actions: List[Dict[str, str]] = field(default_factory=list)


# ── client ──────────────────────────────────────────────────────────


class FeishuClient:
    """Pushes messages to a Feishu incoming webhook."""

    @property
    def is_configured(self) -> bool:
        """Return True when a webhook URL is set."""
        return self._configured

    def __init__(self, webhook_url: Optional[str] = None):
        self._url = webhook_url
        self._configured = bool(webhook_url)
        if self._configured:
            logger.info("FeishuClient configured: %s...", webhook_url[:40])
        else:
            logger.warning("FeishuClient: no webhook_url provided, messages will be logged only")

    # ── public send methods ─────────────────────────────────────────

    def send_alert(self, title: str, content: str, severity: str = "P1") -> bool:
        """Send a simple alert card."""
        return self.send(
            FeishuMessage(title=title, content=content, severity=severity)
        )

    def send_daily_report(self, title: str, sections: Dict[str, str]) -> bool:
        """Send a daily check report with multiple sections."""
        content_parts = []
        for section_title, section_body in sections.items():
            content_parts.append(f"**{section_title}**\n{section_body}")
        return self.send(
            FeishuMessage(
                title=title,
                content="\n\n".join(content_parts),
                severity="P2",
                tags=["日报"],
            )
        )

    def send_weekly_report(self, title: str, sections: Dict[str, str]) -> bool:
        """Send a weekly summary report."""
        content_parts = []
        for section_title, section_body in sections.items():
            content_parts.append(f"**{section_title}**\n{section_body}")
        return self.send(
            FeishuMessage(
                title=title,
                content="\n\n".join(content_parts),
                severity="P2",
                tags=["周报"],
            )
        )

    def send(self, message: FeishuMessage) -> bool:
        """Send a card message to the configured webhook.

        Falls back to logging when no webhook is configured.
        """
        payload = self._build_card(message)
        if not self._configured:
            logger.info(
                "Feishu (log-only) [%s] %s: %s",
                message.severity,
                message.title,
                message.content[:150],
            )
            return True

        try:
            resp = requests.post(
                self._url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") != 0 and result.get("StatusCode") != 0:
                logger.error("Feishu API returned error: %s", result)
                return False
            logger.info("Feishu message sent: %s", message.title)
            return True
        except Exception as exc:
            logger.error("Feishu send failed: %s", exc)
            return False

    # ── card builder ────────────────────────────────────────────────

    def _build_card(self, message: FeishuMessage) -> Dict[str, Any]:
        color = SEVERITY_COLORS.get(message.severity, "blue")
        severity_label = SEVERITY_LABELS.get(message.severity, message.severity)

        elements: List[Dict] = [
            {
                "tag": "markdown",
                "content": message.content or "",
            }
        ]

        if message.tags or message.actions:
            hr_elements: List[Dict] = [{"tag": "hr"}]
            if message.tags:
                hr_elements.append({
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": " | ".join(message.tags)}],
                })
            if message.actions:
                action_text = "  ".join(
                    f"[{a.get('label', 'Action')}]({a.get('url', '')})"
                    for a in message.actions
                )
                hr_elements.append({
                    "tag": "markdown",
                    "content": action_text,
                })
            elements.extend(hr_elements)

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{severity_label} {message.title}",
                    },
                    "template": color,
                },
                "elements": elements,
            },
        }

    # ── factory ─────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "FeishuClient":
        """Create a client from FEISHU_WEBHOOK_URL env var."""
        import os

        url = os.getenv("FEISHU_WEBHOOK_URL", "")
        return cls(webhook_url=url if url else None)
