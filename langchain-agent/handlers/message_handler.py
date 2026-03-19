"""message_handler.py — Slack @mention event handler."""
import json
import logging
import re

from agent.memory import get_memory
from formatters.slack_formatter import format_agent_response, format_approval_request
from handlers.approval_handler import create_approval_request

logger = logging.getLogger(__name__)

_APPROVAL_RE = re.compile(
    r"<APPROVAL_REQUEST>\s*(\{.*?\})\s*</APPROVAL_REQUEST>", re.DOTALL
)


def _strip_mention(text: str) -> str:
    """Remove <@BOTID> mention prefix from message text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _extract_approval(text: str) -> tuple[str, dict | None]:
    """
    Extract <APPROVAL_REQUEST> JSON block from agent output.
    Returns (clean_text, approval_dict | None).
    """
    match = _APPROVAL_RE.search(text)
    if not match:
        return text, None
    try:
        approval = json.loads(match.group(1))
        clean = _APPROVAL_RE.sub("", text).strip()
        return clean, approval
    except json.JSONDecodeError:
        return text, None


def register_handlers(app, agent_fn) -> None:
    """Register Slack Bolt event handlers."""

    @app.event("app_mention")
    async def handle_mention(event, say, client):
        channel = event["channel"]
        ts = event.get("ts")
        thread_ts = event.get("thread_ts", ts)
        user_text = _strip_mention(event.get("text", ""))

        if not user_text:
            await say(text="무엇을 도와드릴까요?", thread_ts=thread_ts)
            return

        logger.info("Agent invoked channel=%s user=%s input=%s", channel, event.get("user"), user_text[:80])

        # "thinking..." reaction
        try:
            await client.reactions_add(channel=channel, timestamp=ts, name="thinking_face")
        except Exception:
            pass

        try:
            memory = get_memory(channel)
            result = await agent_fn(user_text, channel_id=channel, memory=memory)
            output: str = result.get("output", "응답을 생성하지 못했습니다.")

            clean_text, approval = _extract_approval(output)

            # Also search intermediate steps in case LLM didn't include the block in Final Answer
            if not approval:
                for _action, observation in result.get("intermediate_steps", []):
                    if isinstance(observation, str):
                        _, approval = _extract_approval(observation)
                        if approval:
                            break

            # Send main response
            msg = format_agent_response(clean_text, thread_ts=thread_ts)
            resp = await client.chat_postMessage(channel=channel, **msg)

            # Send approval block if needed
            if approval:
                request_id = create_approval_request(
                    action=approval.get("action", "unknown"),
                    description=approval.get("description", ""),
                    params=approval.get("params", {}),
                    reason=approval.get("reason", ""),
                    channel=channel,
                    message_ts=resp["ts"],
                )
                approval_msg = format_approval_request(
                    description=approval.get("description", ""),
                    reason=approval.get("reason", ""),
                    action=approval.get("action", ""),
                    params=approval.get("params", {}),
                    request_id=request_id,
                )
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    **approval_msg,
                )

        except Exception as e:
            logger.error("Agent error: %s", e, exc_info=True)
            await say(text=f"에러가 발생했습니다: `{e}`", thread_ts=thread_ts)
        finally:
            try:
                await client.reactions_remove(channel=channel, timestamp=ts, name="thinking_face")
            except Exception:
                pass
