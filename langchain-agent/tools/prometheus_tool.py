"""prometheus_tool.py — Prometheus HTTP API wrapper as LangChain tools."""
import logging
from typing import Any

import requests
from langchain.tools import tool

import config as cfg

logger = logging.getLogger(__name__)


def _query(promql: str, params: dict[str, Any]) -> dict:
    resp = requests.get(
        f"{cfg.PROMETHEUS_URL}/api/v1/query",
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


@tool
def query_metric(promql: str) -> str:
    """Query CPU/memory/network metrics from Prometheus using PromQL. ALWAYS use this tool when asked about CPU utilization, memory usage, or any resource metrics.
    Pass only the PromQL expression as a plain string.
    Example for CPU: query_metric('sum(rate(container_cpu_usage_seconds_total{namespace="flooding",container!=""}[5m])) by (pod)')
    Example for memory: query_metric('sum(container_memory_working_set_bytes{namespace="flooding",container!=""}) by (pod)')"""
    promql = promql.strip().strip("'\"")
    logger.info("prometheus query_metric promql=%s", promql)
    try:
        data = _query(promql, {"query": promql})
        data_block = data.get("data", {})
        result_type = data_block.get("resultType", "vector")
        results = data_block.get("result", [])
        if not results:
            return f"No data returned for query: {promql}"
        if result_type == "scalar":
            return f"scalar: {results[1] if len(results) > 1 else results}"
        lines = []
        for r in results[:20]:
            if not isinstance(r, dict):
                continue
            metric = ", ".join(f'{k}="{v}"' for k, v in r.get("metric", {}).items())
            value = r.get("value", [None, "?"])[1]
            lines.append(f"{metric}: {value}")
        return "\n".join(lines) if lines else f"No data returned for query: {promql}"
    except requests.RequestException as e:
        return f"Prometheus request error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def get_alerts(filter_labels: str = "") -> str:
    """Fetch currently firing alerts from Alertmanager API.
    filter_labels is optional and can be left empty."""
    logger.info("prometheus get_alerts")
    try:
        resp = requests.get(
            f"{cfg.PROMETHEUS_URL.replace(':9090', ':9093')}/api/v2/alerts",
            timeout=10,
        )
        resp.raise_for_status()
        alerts = resp.json()
        if not alerts:
            return "No active alerts."
        lines = ["Active Alerts:"]
        for a in alerts:
            name = a.get("labels", {}).get("alertname", "unknown")
            severity = a.get("labels", {}).get("severity", "?")
            ns = a.get("labels", {}).get("namespace", "-")
            ann = a.get("annotations", {}).get("description", "")
            lines.append(f"  [{severity.upper()}] {name} (ns={ns}): {ann}")
        return "\n".join(lines)
    except requests.RequestException as e:
        return f"Alertmanager request error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def get_service_error_rate(service: str, duration: str = "5m") -> str:
    """Get HTTP 5xx error rate for a service over the given duration."""
    logger.info("prometheus get_service_error_rate service=%s duration=%s", service, duration)
    promql = (
        f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[{duration}])) / '
        f'sum(rate(http_requests_total{{service="{service}"}}[{duration}]))'
    )
    try:
        data = _query(promql, {"query": promql})
        results = data.get("data", {}).get("result", [])
        if not results:
            return f"No error rate data for service '{service}'. It may not expose http_requests_total metric."
        value = float(results[0].get("value", [None, 0])[1])
        pct = value * 100
        status = "CRITICAL" if pct > 5 else "WARNING" if pct > 1 else "OK"
        return f"Service '{service}' error rate ({duration}): {pct:.2f}% [{status}]"
    except requests.RequestException as e:
        return f"Prometheus request error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"
