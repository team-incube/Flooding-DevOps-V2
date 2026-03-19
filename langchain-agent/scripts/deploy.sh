#!/usr/bin/env bash
# deploy.sh — 로컬에서 실행. 소스를 gsmsv-1로 전송하고 이미지 빌드/푸시/재배포.
# 사용법: bash scripts/deploy.sh

set -euo pipefail

REMOTE_HOST="gsmsv-1.yujun.kr"
REMOTE_PORT="27101"
REMOTE_USER="ubuntu"
REMOTE_DIR="/tmp/infra-agent"
HARBOR="gsmsv-1.yujun.kr:28104"
IMAGE="${HARBOR}/flooding/infra-agent:latest"
NAMESPACE="flooding"
DEPLOY="infra-agent"

echo "=== [1/4] 소스 전송 ==="
# .dockerignore 대상 제외하면서 전송
rsync -avz --delete \
  --exclude='.git/' \
  --exclude='app/' \
  --exclude='k8s/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='scripts/' \
  -e "ssh -p ${REMOTE_PORT}" \
  "$(dirname "$0")/../" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

echo "=== [2/4] 이미지 빌드 ==="
ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" \
  "sudo nerdctl --address /run/containerd/containerd.sock build \
    --insecure-registry \
    -t '${IMAGE}' \
    '${REMOTE_DIR}'"

echo "=== [3/4] 이미지 Push ==="
ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" \
  "sudo nerdctl --address /run/containerd/containerd.sock push \
    --insecure-registry '${IMAGE}'"

echo "=== [4/4] 배포 재시작 ==="
ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" \
  "KUBECONFIG=/home/ubuntu/.kube/config kubectl rollout restart \
    deployment/${DEPLOY} -n ${NAMESPACE} && \
   KUBECONFIG=/home/ubuntu/.kube/config kubectl rollout status \
    deployment/${DEPLOY} -n ${NAMESPACE} --timeout=120s"

echo ""
echo "✅ 배포 완료! 로그 확인:"
echo "  ssh -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST} \\"
echo "    'kubectl logs -n ${NAMESPACE} -l app=${DEPLOY} --tail=50 -f'"
