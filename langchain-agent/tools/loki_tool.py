"""loki_tool.py — Loki LogQL HTTP API wrapper as LangChain tools."""
import logging
import time
from collections import Counter

import requests
from langchain.tools import tool

import config as cfg

logger = logging.getLogger(__name__)

_DURATION_TO_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "3h": 10800, "6h": 21600}


def _now_ns() -> int:
    return int(time.time() * 1e9)


def _start_ns(duration: str) -> int:
    seconds = _DURATION_TO_SECONDS.get(duration, 3600)
    return int((time.time() - seconds) * 1e9)


@tool
def query_logs(logql: str, limit: int = 50, duration: str = "1h") -> str:
    """Execute a LogQL query against Loki. Returns the last N matching log lines."""
    logger.info("loki query_logs logql=%s limit=%d duration=%s", logql, limit, duration)
    try:
        resp = requests.get(
            f"{cfg.LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "limit": limit,
                "start": _start_ns(duration),
                "end": _now_ns(),
                "direction": "backward",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        streams = data.get("data", {}).get("result", [])
        if not streams:
            return f"No logs found for query: {logql}"
        lines = []
        for stream in streams:
            labels = stream.get("stream", {})
            pod = labels.get("pod", labels.get("container", "unknown"))
            for ts, line in stream.get("values", []):
                ts_sec = int(ts) // int(1e9)
                lines.append((ts_sec, pod, line))
        lines.sort(key=lambda x: x[0])
        return "\n".join(f"[{pod}] {line}" for _, pod, line in lines[-limit:])
    except requests.RequestException as e:
        return f"Loki request error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def get_error_logs(namespace: str, duration: str = "30m") -> str:
    """Fetch ERROR/EXCEPTION level logs for a namespace, deduplicated with counts."""
    logger.info("loki get_error_logs namespace=%s duration=%s", namespace, duration)
    logql = f'{{namespace="{namespace}"}} |~ "(?i)(ERROR|EXCEPTION|FATAL)"'
    try:
        resp = requests.get(
            f"{cfg.LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "limit": 200,
                "start": _start_ns(duration),
                "end": _now_ns(),
                "direction": "backward",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        streams = data.get("data", {}).get("result", [])
        if not streams:
            return f"No error logs found in namespace '{namespace}' for the last {duration}."
        raw_lines = []
        for stream in streams:
            for _, line in stream.get("values", []):
                raw_lines.append(line[:200])
        counter: Counter = Counter(raw_lines)
        lines = [f"Top errors in namespace '{namespace}' (last {duration}):"]
        for msg, count in counter.most_common(10):
            lines.append(f"  x{count:>4}  {msg}")
        return "\n".join(lines)
    except requests.RequestException as e:
        return f"Loki request error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"
