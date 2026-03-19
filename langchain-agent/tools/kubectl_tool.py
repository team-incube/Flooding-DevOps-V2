"""kubectl_tool.py — Kubernetes Python client wrapper as LangChain tools."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException
from langchain.tools import tool

import config as cfg

logger = logging.getLogger(__name__)


def _load_kube_config() -> None:
    """Load kubeconfig: in-cluster first, fallback to file."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config(config_file=cfg.KUBECONFIG_PATH or None)


_load_kube_config()


class RequiresApprovalError(Exception):
    """Raised when a destructive action needs Slack approval before execution."""

    def __init__(self, action: str, description: str, params: dict, reason: str = "") -> None:
        self.action = action
        self.description = description
        self.params = params
        self.reason = reason
        super().__init__(f"REQUIRES_APPROVAL:{action}")


@tool
def get_pod_status(namespace: str = "default") -> str:
    """List all pods in a namespace with status, restarts, and age.
    Example: get_pod_status("flooding") or get_pod_status("monitoring")
    Pass only the namespace name as a plain string."""
    logger.info("kubectl get_pod_status namespace=%s", namespace)
    try:
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace)
        if not pods.items:
            return f"No pods found in namespace '{namespace}'."
        lines = [f"{'NAME':<50} {'STATUS':<20} {'RESTARTS':<10} {'AGE'}"]
        lines.append("-" * 90)
        for pod in pods.items:
            name = pod.metadata.name
            phase = pod.status.phase or "Unknown"
            restarts = sum(
                cs.restart_count
                for cs in (pod.status.container_statuses or [])
            )
            created = pod.metadata.creation_timestamp
            age = _age(created)
            lines.append(f"{name:<50} {phase:<20} {restarts:<10} {age}")
        result = "\n".join(lines)
        logger.info("get_pod_status returned %d pods", len(pods.items))
        return result
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def get_node_status(label_selector: str = "") -> str:
    """List all nodes with CPU/memory allocatable vs capacity.
    label_selector is optional and can be left empty."""
    logger.info("kubectl get_node_status")
    try:
        v1 = client.CoreV1Api()
        nodes = v1.list_node()
        lines = [f"{'NAME':<20} {'ROLE':<20} {'STATUS':<12} {'CPU':<10} {'MEMORY'}"]
        lines.append("-" * 80)
        for node in nodes.items:
            name = node.metadata.name
            labels = node.metadata.labels or {}
            role = "control-plane" if "node-role.kubernetes.io/control-plane" in labels else "worker"
            ready = next(
                (c.status for c in (node.status.conditions or []) if c.type == "Ready"),
                "Unknown",
            )
            cpu = node.status.allocatable.get("cpu", "?")
            mem = node.status.allocatable.get("memory", "?")
            lines.append(f"{name:<20} {role:<20} {ready:<12} {cpu:<10} {mem}")
        return "\n".join(lines)
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def get_events(namespace: str = "default", limit: int = 20) -> str:
    """Get recent Warning events from Kubernetes for a namespace.
    Example: get_events("flooding") or get_events("monitoring", 10)
    Pass only the namespace name as a plain string."""
    logger.info("kubectl get_events namespace=%s limit=%d", namespace, limit)
    try:
        v1 = client.CoreV1Api()
        events = v1.list_namespaced_event(namespace, field_selector="type=Warning")
        items = sorted(
            events.items,
            key=lambda e: e.last_timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:limit]
        if not items:
            return f"No Warning events in namespace '{namespace}'."
        lines = [f"{'TIME':<25} {'OBJECT':<40} {'REASON':<20} MESSAGE"]
        lines.append("-" * 110)
        for ev in items:
            ts = str(ev.last_timestamp)[:19] if ev.last_timestamp else "unknown"
            obj = f"{ev.involved_object.kind}/{ev.involved_object.name}"
            reason = ev.reason or ""
            msg = (ev.message or "")[:60]
            lines.append(f"{ts:<25} {obj:<40} {reason:<20} {msg}")
        return "\n".join(lines)
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def describe_pod(pod_name: str, namespace: str = "default") -> str:
    """kubectl describe pod — returns events, conditions, container states."""
    logger.info("kubectl describe_pod pod=%s namespace=%s", pod_name, namespace)
    try:
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(pod_name, namespace)
        lines = [f"Pod: {pod.metadata.name}", f"Namespace: {namespace}",
                 f"Node: {pod.spec.node_name}", f"Phase: {pod.status.phase}"]

        lines.append("\nConditions:")
        for cond in (pod.status.conditions or []):
            lines.append(f"  {cond.type}: {cond.status} — {cond.message or ''}")

        lines.append("\nContainers:")
        for cs in (pod.status.container_statuses or []):
            lines.append(f"  {cs.name}: ready={cs.ready} restarts={cs.restart_count}")
            if cs.state.waiting:
                lines.append(f"    Waiting: {cs.state.waiting.reason} — {cs.state.waiting.message or ''}")
            if cs.state.terminated:
                lines.append(f"    Terminated: {cs.state.terminated.reason} exit={cs.state.terminated.exit_code}")
            if cs.last_state.terminated:
                lines.append(f"    LastTerminated: {cs.last_state.terminated.reason}")

        lines.append("\nEvents:")
        events = v1.list_namespaced_event(
            namespace,
            field_selector=f"involvedObject.name={pod_name}",
        )
        for ev in sorted(events.items, key=lambda e: e.last_timestamp or datetime.min.replace(tzinfo=timezone.utc)):
            lines.append(f"  [{ev.type}] {ev.reason}: {ev.message}")

        return "\n".join(lines)
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def get_pod_logs(namespace: str, pod_name: str = "", tail: int = 20, container: str = "") -> str:
    """Get recent logs from a pod using kubectl logs.
    pod_name can be the full pod name OR a deployment/app name prefix (e.g. "flooding-server").
    Automatically finds the first running pod matching the prefix.
    Example: get_pod_logs(namespace="flooding", pod_name="flooding-server", tail=5)"""
    logger.info("kubectl get_pod_logs namespace=%s pod=%s tail=%d", namespace, pod_name, tail)
    try:
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace)
        running = [p for p in pods.items if p.status.phase == "Running"]
        if not running:
            return f"No running pods found in namespace '{namespace}'."

        if pod_name:
            # Try exact match first, then prefix match
            match = next((p for p in running if p.metadata.name == pod_name), None)
            if not match:
                match = next((p for p in running if p.metadata.name.startswith(pod_name)), None)
            if not match:
                names = [p.metadata.name for p in running]
                return f"No running pod matching '{pod_name}'. Running pods: {', '.join(names)}"
            target_pod = match.metadata.name
        else:
            target_pod = running[0].metadata.name

        kwargs = {"tail_lines": tail, "timestamps": True}
        if container:
            kwargs["container"] = container
        logs = v1.read_namespaced_pod_log(target_pod, namespace, **kwargs)
        if not logs:
            return f"No logs found for pod '{target_pod}'."
        return f"[{target_pod}]\n{logs}"
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


@tool
def scale_deployment(name: str, replicas: int, namespace: str = "flooding") -> str:
    """Scale a Kubernetes deployment to a given number of replicas. REQUIRES APPROVAL.
    'replicas' is the TARGET total count, not a delta.
    Call get_pod_status first to find the current count, then pass current+N as replicas."""
    approval = {
        "action": "scale_deployment",
        "description": f"Scale deployment '{name}' in '{namespace}' to {replicas} replicas",
        "params": {"name": name, "namespace": namespace, "replicas": replicas},
        "reason": "Requested by agent to address workload issue",
    }
    return f"<APPROVAL_REQUEST>\n{json.dumps(approval, indent=2)}\n</APPROVAL_REQUEST>"


@tool
def restart_deployment(name: str, namespace: str = "flooding") -> str:
    """Rolling restart of a Kubernetes deployment. REQUIRES APPROVAL."""
    approval = {
        "action": "restart_deployment",
        "description": f"Rolling restart deployment '{name}' in '{namespace}'",
        "params": {"name": name, "namespace": namespace},
        "reason": "Requested by agent to recover from unhealthy state",
    }
    return f"<APPROVAL_REQUEST>\n{json.dumps(approval, indent=2)}\n</APPROVAL_REQUEST>"


def execute_scale_deployment(name: str, namespace: str, replicas: int) -> str:
    """Execute scale (called AFTER approval)."""
    try:
        apps = client.AppsV1Api()
        body = {"spec": {"replicas": replicas}}
        apps.patch_namespaced_deployment_scale(name, namespace, body)
        logger.info("Scaled %s/%s to %d replicas", namespace, name, replicas)
        return f"Scaled deployment '{name}' to {replicas} replicas successfully."
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


def execute_restart_deployment(name: str, namespace: str) -> str:
    """Execute rolling restart (called AFTER approval)."""
    try:
        apps = client.AppsV1Api()
        now = datetime.now(timezone.utc).isoformat()
        body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}
        apps.patch_namespaced_deployment(name, namespace, body)
        logger.info("Restarted deployment %s/%s", namespace, name)
        return f"Deployment '{name}' rolling restart triggered."
    except ApiException as e:
        return f"kubectl error: {e.status} {e.reason}"
    except Exception as e:
        return f"Unexpected error: {e}"


def _age(ts: Optional[datetime]) -> str:
    if not ts:
        return "unknown"
    delta = datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else datetime.now(timezone.utc) - ts
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"{h}h{m}m" if h else f"{m}m"
