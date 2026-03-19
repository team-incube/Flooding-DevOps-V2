"""orchestrator.py — LangChain OpenAI Tools AgentExecutor builder."""
import logging

from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

import config as cfg
from agent.prompts import SYSTEM_PROMPT
from tools.kubectl_tool import (
    get_pod_status, get_node_status, get_events,
    describe_pod, get_pod_logs, scale_deployment, restart_deployment,
)
from tools.prometheus_tool import query_metric, get_alerts, get_service_error_rate
from tools.loki_tool import query_logs, get_error_logs
from tools.helm_tool import get_release_history, rollback_release, get_current_values
from tools.runbook_tool import match_runbook

logger = logging.getLogger(__name__)

ALL_TOOLS = [
    get_pod_status,
    get_node_status,
    get_events,
    describe_pod,
    get_pod_logs,
    scale_deployment,
    restart_deployment,
    query_metric,
    get_alerts,
    get_service_error_rate,
    query_logs,
    get_error_logs,
    get_release_history,
    rollback_release,
    get_current_values,
    match_runbook,
]


def build_agent() -> AgentExecutor:
    """Build and return the LangChain OpenAI Tools AgentExecutor."""
    llm = ChatOpenAI(
        model=cfg.OPENAI_MODEL,
        temperature=0,
        api_key=cfg.OPENAI_API_KEY,
    )

    # Use SystemMessage object (not a string tuple) so the system prompt content
    # is never parsed for template variables — avoids issues with {curly} braces
    # in PromQL examples or JSON snippets inside SYSTEM_PROMPT.
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history", optional=True),
        HumanMessagePromptTemplate.from_template("{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm=llm, tools=ALL_TOOLS, prompt=prompt)

    executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=15,
        verbose=True,
        return_intermediate_steps=True,
    )
    logger.info("AgentExecutor built with %d tools", len(ALL_TOOLS))
    return executor


# Singleton
_agent: AgentExecutor | None = None


def get_agent() -> AgentExecutor:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent
