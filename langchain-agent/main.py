"""main.py — Entry point: Slack Bolt (Socket Mode) + FastAPI concurrently."""
import asyncio
import logging

from fastapi import FastAPI
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

import config as cfg
from agent.memory import get_memory
from agent.orchestrator import get_agent
from handlers import alert_handler, approval_handler, message_handler

logger = logging.getLogger(__name__)

# ── Slack Bolt App ────────────────────────────────────────────────────────────
bolt_app = AsyncApp(
    token=cfg.SLACK_BOT_TOKEN,
    signing_secret=cfg.SLACK_SIGNING_SECRET,
)

# ── FastAPI App ───────────────────────────────────────────────────────────────
api = FastAPI(title="Flooding Infra Agent", version="1.0.0")
api.include_router(alert_handler.router)


# ── Agent wrapper (async) ─────────────────────────────────────────────────────
_VAGUE_PHRASES = ("provided above", "shown above", "listed above", "as above", "see above")
_ITERATION_LIMIT_MSG = "agent stopped due to iteration limit or time limit"


def _enrich_output(result: dict) -> dict:
    """Improve vague or truncated agent outputs."""
    output = result.get("output", "")
    steps = result.get("intermediate_steps", [])

    # Replace iteration-limit message with last meaningful tool result
    if _ITERATION_LIMIT_MSG in output.lower():
        useful = [
            (action, obs) for action, obs in steps
            if isinstance(obs, str) and len(obs) > 10
        ]
        if useful:
            action, obs = useful[-1]
            result["output"] = (
                f"분석 중 반복 한도에 도달했습니다. 마지막으로 수집한 정보:\n\n"
                f"*{action.tool}*\n```\n{obs}\n```"
            )
        else:
            result["output"] = "요청을 처리하는 중 시간이 초과되었습니다. 더 구체적인 질문으로 다시 시도해 주세요."
        return result

    # Replace vague references with actual tool results
    if not any(p in output.lower() for p in _VAGUE_PHRASES):
        return result
    parts = []
    for action, observation in steps:
        if observation and isinstance(observation, str) and len(observation) > 10:
            parts.append(f"*{action.tool}*\n```\n{observation}\n```")
    if parts:
        result["output"] = "\n\n".join(parts)
    return result


async def run_agent(text: str, channel_id: str = "default", memory=None) -> dict:
    """Run agent in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    agent = get_agent()
    mem = memory or get_memory(channel_id)

    def _invoke():
        return agent.invoke({
            "input": text,
            "chat_history": mem.chat_memory.messages,
        })

    result = await loop.run_in_executor(None, _invoke)
    result = _enrich_output(result)
    mem.save_context({"input": text}, {"output": result.get("output", "")})
    return result


# ── Register handlers ─────────────────────────────────────────────────────────
message_handler.register_handlers(bolt_app, run_agent)
approval_handler.register_handlers(bolt_app)
alert_handler.init(
    slack_client=None,  # set after bolt_app init
    agent_fn=run_agent,
)


# ── Startup ───────────────────────────────────────────────────────────────────
async def main() -> None:
    logger.info("Starting Flooding Infra Agent...")

    # Pre-warm agent
    get_agent()

    # Inject async slack client for alert_handler
    alert_handler._slack_client = bolt_app.client

    # Socket Mode handler (Slack)
    socket_handler = AsyncSocketModeHandler(bolt_app, cfg.SLACK_APP_TOKEN)

    # Run FastAPI + Socket Mode concurrently
    import uvicorn
    server = uvicorn.Server(
        uvicorn.Config(api, host="0.0.0.0", port=cfg.APP_PORT, log_level="info")
    )

    await asyncio.gather(
        socket_handler.start_async(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
