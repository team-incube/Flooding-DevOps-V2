#!/usr/bin/env bash
# create-flooding-secret.sh — gsmsv-1에서 실행.
# flooding-server에 필요한 k8s secret 생성.
# 사용법: bash create-flooding-secret.sh

set -euo pipefail

NAMESPACE="flooding"

echo "=== flooding-server-secret 생성 ==="
kubectl create secret generic flooding-server-secret \
  --from-literal=DB_URL="jdbc:postgresql://postgres.flooding.svc:5432/flooding" \
  --from-literal=DB_USERNAME="flooding" \
  --from-literal=DB_PASSWORD="***REMOVED***" \
  --from-literal=DB_DRIVER="org.postgresql.Driver" \
  --from-literal=JPA_DDL_AUTO="update" \
  --from-literal=JPA_DIALECT="org.hibernate.dialect.PostgreSQLDialect" \
  --from-literal=REDIS_HOST="redis.flooding.svc" \
  --from-literal=REDIS_PORT="6379" \
  --from-literal=JWT_SECRET="flooding-jwt-secret-key-2026-must-be-at-least-32-chars" \
  --from-literal=JWT_ACCESS_EXPIRATION="3600000" \
  --from-literal=JWT_REFRESH_EXPIRATION="604800000" \
  --from-literal=OAUTH_CLIENT_ID="<REPLACE_ME>" \
  --from-literal=OAUTH_CLIENT_SECRET="<REPLACE_ME>" \
  --namespace="${NAMESPACE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ flooding-server-secret 생성 완료"
echo ""
echo "⚠️  OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET 는 수동으로 업데이트 필요:"
echo "  kubectl edit secret flooding-server-secret -n ${NAMESPACE}"
