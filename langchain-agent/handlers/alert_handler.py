"""alert_handler.py — FastAPI endpoint for Alertmanager webhooks."""
import logging

from fastapi import APIRouter

import config as cfg
from formatters.slack_formatter import format_alert_summary

logger = logging.getLogger(__name__)
router = APIRouter()

# Will be injected from main.py
_slack_client = None
_agent_fn = None


def init(slack_client, agent_fn) -> None:
    global _slack_client, _agent_fn
    _slack_client = slack_client
    _agent_fn = agent_fn


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/webhook/alertmanager")
async def receive_alert(payload: dict):
    """Receive Alertmanager webhook and run agent analysis for each firing alert."""
    alerts = payload.get("alerts", [])
    firing = [a for a in alerts if a.get("status") == "firing"]
    logger.info("Alertmanager webhook received: %d firing alerts", len(firing))

    for alert in firing:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alertname = labels.get("alertname", "UnknownAlert")
        namespace = labels.get("namespace", "unknown")
        pod = labels.get("pod", "")
        severity = labels.get("severity", "warning")
        description = annotations.get("description", annotations.get("summary", "No description"))

        prompt = (
            f"ALERT: {alertname} in namespace {namespace}\n"
            f"Pod: {pod}\n"
            f"Severity: {severity}\n"
            f"Message: {description}\n\n"
            "Investigate and propose a concrete solution."
        )

        logger.info("Running agent for alert: %s", alertname)
        try:
            result = await _agent_fn(prompt, channel_id="alertmanager")
            analysis = result.get("output", "Agent produced no output.")
        except Exception as e:
            logger.error("Agent failed for alert %s: %s", alertname, e)
            analysis = f"Agent error: {e}"

        if _slack_client:
            msg = format_alert_summary(alertname, severity, namespace, analysis)
            try:
                await _slack_client.chat_postMessage(
                    channel=cfg.SLACK_ALERT_CHANNEL,
                    **msg,
                )
            except Exception as e:
                logger.error("Failed to post alert to Slack: %s", e)

    return {"status": "ok", "processed": len(firing)}
