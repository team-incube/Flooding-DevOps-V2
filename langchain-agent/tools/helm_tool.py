"""helm_tool.py — Helm CLI subprocess wrapper as LangChain tools."""
import json
import logging
import subprocess

from langchain.tools import tool


logger = logging.getLogger(__name__)


def _helm(*args: str) -> str:
    cmd = ["helm", *args]
    logger.info("helm cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return f"helm error: {result.stderr.strip()}"
    return result.stdout.strip()


@tool
def get_release_history(release: str, namespace: str) -> str:
    """List helm release revision history."""
    logger.info("helm get_release_history release=%s namespace=%s", release, namespace)
    try:
        return _helm("history", release, "-n", namespace, "--max", "10", "-o", "table")
    except subprocess.TimeoutExpired:
        return "helm history timed out"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def rollback_release(release: str, namespace: str, revision: int = 0) -> str:
    """Rollback a Helm release to a previous revision. REQUIRES APPROVAL. revision=0 means previous."""
    rev_label = str(revision) if revision else "previous"
    approval = {
        "action": "helm_rollback",
        "description": f"Rollback Helm release '{release}' in '{namespace}' to revision {rev_label}",
        "params": {"release": release, "namespace": namespace, "revision": revision},
        "reason": "Agent detected issue requiring rollback to stable version",
    }
    return f"<APPROVAL_REQUEST>\n{json.dumps(approval, indent=2)}\n</APPROVAL_REQUEST>"


@tool
def get_current_values(release: str, namespace: str) -> str:
    """Get currently deployed Helm values for a release."""
    logger.info("helm get_current_values release=%s namespace=%s", release, namespace)
    try:
        return _helm("get", "values", release, "-n", namespace)
    except subprocess.TimeoutExpired:
        return "helm get values timed out"
    except Exception as e:
        return f"Unexpected error: {e}"


def execute_rollback(release: str, namespace: str, revision: int = 0) -> str:
    """Execute helm rollback (called AFTER approval)."""
    try:
        args = ["rollback", release, "-n", namespace, "--wait"]
        if revision:
            args.insert(2, str(revision))
        result = _helm(*args)
        logger.info("Helm rollback executed: %s/%s rev=%s", namespace, release, revision)
        return result or f"Rollback of '{release}' completed successfully."
    except Exception as e:
        return f"Unexpected error during rollback: {e}"
