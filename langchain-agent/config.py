import os
import logging

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Slack ─────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN: str = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN: str = os.environ["SLACK_APP_TOKEN"]
SLACK_SIGNING_SECRET: str = os.environ["SLACK_SIGNING_SECRET"]
SLACK_ALERT_CHANNEL: str = os.getenv("SLACK_ALERT_CHANNEL", "#infra-alerts")

# ── OpenAI ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Observability endpoints ───────────────────────────────────────────────────
PROMETHEUS_URL: str = os.getenv(
    "PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.monitoring.svc:9090"
)
LOKI_URL: str = os.getenv(
    "LOKI_URL", "http://loki-stack.monitoring.svc:3100"
)

# ── Kubernetes ────────────────────────────────────────────────────────────────
KUBECONFIG_PATH: str = os.getenv("KUBECONFIG_PATH", "")

# ── Approval ──────────────────────────────────────────────────────────────────
APPROVAL_TIMEOUT_SEC: int = int(os.getenv("APPROVAL_TIMEOUT_SEC", "120"))

# ── App ───────────────────────────────────────────────────────────────────────
APP_PORT: int = int(os.getenv("APP_PORT", "8080"))
