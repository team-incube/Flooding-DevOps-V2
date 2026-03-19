"""runbook_tool.py — YAML runbook pattern matcher as LangChain tool."""
import logging
from pathlib import Path

import yaml
from langchain.tools import tool

logger = logging.getLogger(__name__)

_RUNBOOK_PATH = Path(__file__).parent.parent / "runbooks" / "runbook.yaml"


def _load_runbooks() -> list[dict]:
    with open(_RUNBOOK_PATH) as f:
        return yaml.safe_load(f).get("runbooks", [])


_RUNBOOKS = _load_runbooks()


@tool
def match_runbook(symptom: str) -> str:
    """
    Given a symptom string (e.g. 'CrashLoopBackOff', 'OOMKilled', 'error rate > 5%'),
    find matching runbook entries and return diagnosis steps and available actions.
    """
    logger.info("runbook match_runbook symptom=%s", symptom)
    matches = [
        rb for rb in _RUNBOOKS
        if rb["pattern"].lower() in symptom.lower()
        or symptom.lower() in rb["pattern"].lower()
    ]
    if not matches:
        return (
            f"No runbook found for symptom: '{symptom}'.\n"
            "Use kubectl/prometheus/loki tools to investigate manually."
        )
    output = []
    for rb in matches:
        output.append(f"📋 Runbook: {rb['id']} — {rb['description']}")
        output.append("\nDiagnosis steps:")
        for step in rb.get("diagnosis", []):
            output.append(f"  • {step}")
        output.append("\nAvailable actions:")
        for action in rb.get("actions", []):
            approval = "⚠️ REQUIRES APPROVAL" if action.get("requires_approval") else "✅ Auto"
            output.append(f"  [{approval}] {action['type']}: {action['description']}")
        output.append("")
    return "\n".join(output)
