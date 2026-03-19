"""slack_formatter.py — Slack Block Kit message builders."""
import json
from typing import Optional


def format_agent_response(text: str, thread_ts: Optional[str] = None) -> dict:
    """Plain agent response as Slack blocks."""
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text[:3000]},
        }
    ]
    msg: dict = {"blocks": blocks}
    if thread_ts:
        msg["thread_ts"] = thread_ts
    return msg


def format_approval_request(
    description: str,
    reason: str,
    action: str,
    params: dict,
    request_id: str,
) -> dict:
    """Approval message with Approve/Reject buttons."""
    value_payload = json.dumps({"request_id": request_id, "action": action, "params": params})
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "⚠️ Action Required", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{description}*\n_{reason}_"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Action: `{action}`  |  Params: `{json.dumps(params)}`"}
                ],
            },
            {"type": "divider"},
            {
                "type": "actions",
                "block_id": "approval_block",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                        "style": "primary",
                        "action_id": "approve_action",
                        "value": value_payload,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                        "style": "danger",
                        "action_id": "reject_action",
                        "value": value_payload,
                    },
                ],
            },
        ]
    }


def format_alert_summary(
    alertname: str,
    severity: str,
    namespace: str,
    agent_analysis: str,
) -> dict:
    """Color-coded alert notification block with agent analysis."""
    color = "#FF0000" if severity == "critical" else "#FFA500"
    emoji = "🔴" if severity == "critical" else "🟡"
    return {
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} [{severity.upper()}] {alertname}",
                            "emoji": True,
                        },
                    },
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"Namespace: `{namespace}`"}],
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*Agent Analysis:*\n{agent_analysis[:2000]}"},
                    },
                ],
            }
        ]
    }


def format_execution_result(
    action: str,
    success: bool,
    output: str,
    approved_by: str,
) -> dict:
    """Result block after an approved action executes."""
    icon = "✅" if success else "❌"
    status = "succeeded" if success else "failed"
    return {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon} *Action {status}*\n`{action}` approved by *{approved_by}*\n```{output[:1500]}```",
                },
            }
        ]
    }
