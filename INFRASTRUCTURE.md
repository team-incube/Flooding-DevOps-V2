# Flooding Infrastructure 구성

## 1. 서버 노드

| 역할 | 호스트명 | SSH 접속 | Private IP |
|------|----------|----------|------------|
| Control Plane (Master) | gsmsv-1 | `ssh ubuntu@gsmsv-1.yujun.kr -p 27101` | 10.0.0.6 |
| Worker | gsmsv-2 | `ssh ubuntu@gsmsv-1.yujun.kr -p 27102` | 10.0.0.7 |
| Worker | gsmsv-3 | `ssh ubuntu@gsmsv-1.yujun.kr -p 27103` | 10.0.0.8 |
| Worker (Harbor) | gsmsv-4 | `ssh ubuntu@gsmsv-1.yujun.kr -p 27104` | 10.0.0.9 |
| Monitoring | gsmsv-5 | `ssh ubuntu@gsmsv-1.yujun.kr -p 27105` | 10.0.0.10 |

- Kubernetes v1.29
- CNI: Cilium v1.15.3

---

## 2. 클러스터 네임스페이스

| 네임스페이스 | 용도 |
|-------------|------|
| `flooding` | 백엔드 애플리케이션, Redis, PostgreSQL, infra-agent |
| `monitoring` | Prometheus, Grafana, Loki, Alertmanager |
| `harbor` | 컨테이너 이미지 레지스트리 |
| `argocd` | GitOps CD |
| `traefik` | Ingress Controller |

---

## 3. 인프라 컴포넌트

### Harbor (컨테이너 레지스트리)
- 주소: `gsmsv-1.yujun.kr:28104`
- 노드: gsmsv-4 (NodePort 30104)
- 프로젝트: `flooding`
- HTTP insecure registry (TLS 없음)

### ArgoCD (GitOps CD)
- NodePort: 30101
- 소스 레포: `team-incube/Flooding-DevOps-V2` (main 브랜치)
- 자동 sync + selfHeal + prune 활성화

### Traefik (Ingress)
- Chart v27.0.2

### Prometheus Stack (모니터링)
- Chart v58.2.2 (kube-prometheus-stack)
- Loki Stack v2.10.2

---

## 4. 애플리케이션 (`flooding` 네임스페이스)

### flooding-server (Spring Boot)
- 이미지: `gsmsv-1.yujun.kr:28104/flooding/flooding-server-v2:<tag>`
- replicas: 2 (HPA: min 2, max 5, CPU 70%)
- 리소스: requests 250m/512Mi, limits 1000m/1Gi
- Liveness probe: `GET /actuator/health/liveness:8080`
- Readiness probe: `GET /actuator/health/readiness:8080`
- Secret: `flooding-server-secret` (DB, Redis, JWT 등)
- ConfigMap: SERVER_PORT, MANAGEMENT 설정

### PostgreSQL
- 이미지: postgres:16-alpine
- DB/User: `flooding` / Password: `***REMOVED***`
- PVC: 10Gi (local-path)
- Service: `postgres.flooding.svc:5432`

### Redis
- 이미지: redis:7-alpine
- Service: `redis.flooding.svc:6379`

### infra-agent (LangChain AI)
- 이미지: `gsmsv-1.yujun.kr:28104/flooding/infra-agent:latest`
- LLM: GPT-4o
- Slack 알림 채널: `#infra-alerts`
- Prometheus: `http://kube-prometheus-stack-prometheus.monitoring.svc:9090`
- Loki: `http://loki-stack.monitoring.svc:3100`

---

## 5. CI/CD 파이프라인

```
코드 push (master)
    │
    ▼
[GitHub Actions CI] — self-hosted runner (gsmsv-1, label: flooding)
    ├── Test (Gradle, continue-on-error)
    ├── Build JAR → nerdctl build → Harbor push
    │     이미지 태그: {branch}-{short-sha}
    └── Slack 알림
    │
    ▼
[GitHub Actions CD]
    └── Flooding-DevOps-V2/helm/flooding-server/values.yaml 이미지 태그 업데이트
    │
    ▼
[ArgoCD] — DevOps 레포 변경 감지 → 자동 sync → K8s 배포
```

### GitHub Actions Secrets (Flooding-Server-V2)
| Secret | 용도 |
|--------|------|
| `HARBOR_HOST` | Harbor 주소 (`gsmsv-1.yujun.kr:28104`) |
| `HARBOR_USERNAME` | Harbor 로그인 |
| `HARBOR_PASSWORD` | Harbor 로그인 |
| `INFRA_REPO_TOKEN` | DevOps 레포 values.yaml 업데이트용 PAT |
| `SLACK_WEBHOOK_URL` | CI 결과 Slack 알림 |

---

## 6. Self-hosted Runner

- 위치: gsmsv-1 (`/home/ubuntu/actions-runner`)
- 버전: v2.321.0
- Labels: `self-hosted, linux, flooding, x64`
- 실행: systemd 서비스

---

## 7. Kubernetes Secrets

### flooding-server-secret
| 키 | 값 |
|----|-----|
| DB_URL | `jdbc:postgresql://postgres.flooding.svc:5432/flooding` |
| DB_USERNAME | `flooding` |
| DB_PASSWORD | `***REMOVED***` |
| REDIS_HOST | `redis.flooding.svc` |
| REDIS_PORT | `6379` |
| JWT_SECRET | `flooding-jwt-secret-key-2026-must-be-at-least-32-chars` |
| JWT_ACCESS_EXPIRATION | `3600000` (1시간) |
| JWT_REFRESH_EXPIRATION | `604800000` (7일) |
| OAUTH_CLIENT_ID | **수동 설정 필요** |
| OAUTH_CLIENT_SECRET | **수동 설정 필요** |

---

## 8. 현재 알려진 이슈

| 이슈 | 상태 | 해결 방법 |
|------|------|----------|
| flooding-server liveness probe HTTP 403 | 진행 중 | `SecurityConfig.kt`에 `/actuator/**` permitAll 추가 ([#8](https://github.com/team-incube/Flooding-Server-V2/issues/8)) |
| OAUTH_CLIENT_ID/SECRET 미설정 | 진행 중 | `kubectl edit secret flooding-server-secret -n flooding` |
