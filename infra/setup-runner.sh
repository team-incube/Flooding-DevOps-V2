#!/usr/bin/env bash
# setup-runner.sh — gsmsv-1에서 실행. GitHub Actions self-hosted runner 설치.
# 사용법: bash setup-runner.sh <RUNNER_TOKEN>
# 토큰 발급: GitHub > Flooding-Server-V2 > Settings > Actions > Runners > New self-hosted runner

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <RUNNER_TOKEN>"
  exit 1
fi

RUNNER_TOKEN="$1"
RUNNER_VERSION="2.321.0"
RUNNER_DIR="/home/ubuntu/actions-runner"
REPO_URL="https://github.com/team-incube/Flooding-Server-V2"

echo "=== [1/4] 디렉토리 생성 ==="
mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

echo "=== [2/4] Runner 다운로드 ==="
curl -fsSL -o actions-runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz

echo "=== [3/4] Runner 등록 ==="
./config.sh \
  --url "${REPO_URL}" \
  --token "${RUNNER_TOKEN}" \
  --name "gsmsv-1-runner" \
  --labels "self-hosted,linux,flooding,x64" \
  --unattended \
  --replace

echo "=== [4/4] systemd 서비스 등록 ==="
sudo ./svc.sh install ubuntu
sudo ./svc.sh start

echo ""
echo "✅ Runner 설치 완료"
echo "상태 확인: sudo ./svc.sh status"
echo "로그 확인: journalctl -u actions.runner.* -f"
