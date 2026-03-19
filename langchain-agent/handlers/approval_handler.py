"""approval_handler.py — Slack button action handlers + pending approval store."""
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import config as cfg
from formatters.slack_formatter import format_execution_result
from tools.kubectl_tool import execute_scale_deployment, execute_restart_deployment
from tools.helm_tool import execute_rollback

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    request_id: str
    action: str
    params: dict
    description: str
    reason: str
    channel: str
    message_ts: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# In-memory pending approvals store
pending_approvals: dict[str, ApprovalRequest] = {}


def create_approval_request(
    action: str,
    description: str,
    params: dict,
    reason: str,
    channel: str,
    message_ts: str,
) -> str:
    """Create and store a pending approval. Returns request_id."""
    request_id = str(uuid.uuid4())
    pending_approvals[request_id] = ApprovalRequest(
        request_id=request_id,
        action=action,
        params=params,
        description=description,
        reason=reason,
        channel=channel,
        message_ts=message_ts,
    )
    logger.info("Approval request created id=%s action=%s", request_id, action)
    return request_id


def _is_expired(req: ApprovalRequest) -> bool:
    elapsed = (datetime.now(timezone.utc) - req.created_at).total_seconds()
    return elapsed > cfg.APPROVAL_TIMEOUT_SEC


def _execute_action(action: str, params: dict) -> str:
    """Dispatch approved action to the correct executor."""
    if action == "scale_deployment":
        return execute_scale_deployment(**params)
    elif action == "restart_deployment":
        return execute_restart_deployment(**params)
    elif action == "helm_rollback":
        return execute_rollback(**params)
    else:
        return f"Unknown action type: {action}"


def register_handlers(app) -> None:
    """Register Slack Bolt action handlers on the given app."""

    @app.action("approve_action")
    async def handle_approve(ack, body, client):
        await ack()
        user = body["user"]["name"]
        value = json.loads(body["actions"][0]["value"])
        request_id = value["request_id"]
        action = value["action"]
        params = value["params"]

        req = pending_approvals.pop(request_id, None)
        if req is None:
            await client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="⚠️ This approval request has already been processed or expired.",
            )
            return

        if _is_expired(req):
            await client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=f"⏰ Approval request expired after {cfg.APPROVAL_TIMEOUT_SEC}s.",
            )
            return

        logger.info("Action approved: id=%s action=%s by=%s params=%s", request_id, action, user, params)

        await client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"⏳ Executing `{action}`... (approved by {user})",
        )

        try:
            output = _execute_action(action, params)
            success = True
        except Exception as e:
            output = str(e)
            success = False
            logger.error("Action execution failed: %s", e)

        result_msg = format_execution_result(action, success, output, user)
        await client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            **result_msg,
        )

    @app.action("reject_action")
    async def handle_reject(ack, body, client):
        await ack()
        user = body["user"]["name"]
        value = json.loads(body["actions"][0]["value"])
        request_id = value["request_id"]
        action = value["action"]

        pending_approvals.pop(request_id, None)
        logger.info("Action rejected: id=%s action=%s by=%s", request_id, action, user)

        await client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"❌ Action `{action}` rejected by *{user}*.",
        )
