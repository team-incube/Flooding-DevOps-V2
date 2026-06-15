# Flooding Infrastructure 구성

## 1. 서버 노드

| 역할 | 호스트명 | SSH 접속 | Private IP |
|------|----------|----------|------------|
| Control Plane (Master) | flooding-1 | `ssh ubuntu@ssh.gsmsv.site -p 27101` | 10.0.0.6 |
| Worker | flooding-2 | `ssh ubuntu@ssh.gsmsv.site -p 27102` | 10.0.0.7 |
| Worker | flooding-3 | `ssh ubuntu@ssh.gsmsv.site -p 27103` | 10.0.0.8 |
| Worker (Harbor) | flooding-4 | `ssh ubuntu@ssh.gsmsv.site -p 27104` | 10.0.0.9 |
| Monitoring | flooding-5 | `ssh ubuntu@ssh.gsmsv.site -p 27105` | 10.0.0.10 |
| Worker (AI, gsmsv) | gsmsv | `ssh ubuntu@ssh.gsmsv.site -p 27128` | 10.0.0.154 |

- 공인 IP: `158.247.251.109` (ssh.gsmsv.site)
- ~~`gsmsv-1.yujun.kr`~~ → DNS 레코드 삭제됨 (2026-06-15 이후 사용 불가), `ssh.gsmsv.site` 사용
- Kubernetes v1.29
- CNI: Cilium v1.15.3

---

## 2. 클러스터 네임스페이스

| 네임스페이스 | 용도 |
|-------------|------|
| `flooding` | 백엔드 애플리케이션 (prod), Redis, PostgreSQL, infra-agent |
| `flooding-dev` | 백엔드 애플리케이션 (dev) |
| `monitoring` | Prometheus, Grafana, Loki, Alertmanager |
| `harbor` | 컨테이너 이미지 레지스트리 |
| `argocd` | GitOps CD |
| `traefik` | Ingress Controller |
| `cert-manager` | Let's Encrypt TLS 자동 발급 |

---

## 3. 인프라 컴포넌트

### Harbor (컨테이너 레지스트리)
- 외부 주소: `gsmsv-1.yujun.kr:28104` (이미지 태그 기준, DNS 깨짐)
- 노드: flooding-4 (10.0.0.9), NodePort: `30104`
- **containerd 우회 설정** (전체 노드 적용):
  `/etc/containerd/certs.d/gsmsv-1.yujun.kr:28104/hosts.toml` → `http://10.0.0.9:30104`
- 프로젝트: `flooding`
- HTTP insecure registry (TLS 없음)

### ArgoCD (GitOps CD)
- NodePort: 30101
- 소스 레포: `team-incube/Flooding-DevOps-V2` (main 브랜치)
- 자동 sync + selfHeal + prune 활성화

### Traefik (Ingress)
- Chart v27.0.2
- EntryPoint `websecure`: NodePort 32675 (prod, ai)
- EntryPoint `dev`: NodePort 32676 (dev)

### cert-manager
- Let's Encrypt DNS-01 챌린지 (Cloudflare API token)
- ClusterIssuer: `letsencrypt-prod`
- `--dns01-recursive-nameservers=1.1.1.1:53,8.8.8.8:53 --dns01-recursive-nameservers-only` 설정됨

### Cloudflare 라우팅
| 도메인 | Origin Rule | NodePort |
|--------|-------------|----------|
| prod.flooding.kr | → 서버:32675 | Traefik websecure |
| dev.flooding.kr | → 서버:32676 | Traefik dev |
| ai.flooding.kr | → 서버:32675 | Traefik websecure |
| flooding.kr / www.flooding.kr | Vercel | — |

### Prometheus Stack (모니터링)
- Chart v58.2.2 (kube-prometheus-stack)
- Loki Stack v2.10.2

---

## 4. 애플리케이션

### flooding-server (Spring Boot) — `flooding` 네임스페이스
- 이미지: `gsmsv-1.yujun.kr:28104/flooding/flooding-server-v2:<tag>`
- replicas: 2 (HPA: min 2, max 5, CPU 70%)
- 리소스: requests 250m/512Mi, limits 1000m/1Gi
- Liveness probe: `GET /actuator/health/liveness:8080`
- Readiness probe: `GET /actuator/health/readiness:8080`
- Secret: `flooding-server-secret` (DB, Redis, JWT, R2, File 등)
- 도메인: `https://prod.flooding.kr`

### flooding-server (dev) — `flooding-dev` 네임스페이스
- 이미지: `gsmsv-1.yujun.kr:28104/flooding/flooding-server-v2:develop-<sha>`
- replicas: 1
- 도메인: `https://dev.flooding.kr`

### flooding-ai-server — `flooding` 네임스페이스
- 이미지: Harbor 내 flooding-ai 이미지
- 노드: gsmsv (10.0.0.154), nodeSelector: `role=ai`
- 도메인: `https://ai.flooding.kr`
- 포트: 8000
- NumPy 2.x 사용 (X86_V2 빌드, gsmsv 노드에서만 실행 가능)

### PostgreSQL — `flooding` 네임스페이스
- 이미지: postgres:16-alpine
- DB/User: `flooding` / Password: `***REMOVED***`
- PVC: 10Gi (local-path)
- Service: `postgres.flooding.svc:5432`
- prod DB: `flooding`, dev DB: `flooding_dev`

### Redis — `flooding` 네임스페이스
- 이미지: redis:7-alpine
- Service: `redis.flooding.svc:6379`

### infra-agent (LangChain AI) — `flooding` 네임스페이스
- 이미지: `gsmsv-1.yujun.kr:28104/flooding/infra-agent:latest`
- LLM: GPT-4o
- Slack 알림 채널: `#infra-alerts`
- Prometheus: `http://kube-prometheus-stack-prometheus.monitoring.svc:9090`
- Loki: `http://loki-stack.monitoring.svc:3100`

---

## 5. CI/CD 파이프라인

```
코드 push (master/develop)
    │
    ▼
[GitHub Actions CI] — self-hosted runner (flooding-1, label: flooding)
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

- 위치: flooding-1 (`/home/ubuntu/actions-runner`)
- 버전: v2.321.0
- Labels: `self-hosted, linux, flooding, x64`
- 실행: systemd 서비스
- **주의**: iptables OUTPUT REDIRECT 규칙이 있으면 GitHub 443 포트가 차단됨
  - 확인: `sudo iptables -t nat -L OUTPUT --line-numbers`
  - 제거: `sudo iptables -t nat -D OUTPUT <번호>`

---

## 7. Kubernetes Secrets

### flooding-server-secret (prod: `flooding` ns / dev: `flooding-dev` ns)
| 키 | 값 |
|----|-----|
| DB_URL | `jdbc:postgresql://postgres.flooding.svc:5432/flooding` (dev: `flooding_dev`) |
| DB_USERNAME | `flooding` |
| DB_PASSWORD | `***REMOVED***` |
| REDIS_HOST | `redis.flooding.svc` |
| REDIS_PORT | `6379` |
| JWT_SECRET | `flooding-jwt-secret-key-2026-must-be-at-least-32-chars` |
| JWT_ACCESS_EXPIRATION | `3600000` (1시간) |
| JWT_REFRESH_EXPIRATION | `604800000` (7일) |
| AI_CHATBOT_URL | `http://flooding-ai.flooding.svc:8000` |
| AI_SONG_URL | `http://flooding-ai.flooding.svc:8000` |
| FILE_UPLOAD_DIR | `/app/uploads` |
| FILE_BASE_URL | `https://prod.flooding.kr/` (dev: `https://dev.flooding.kr/`) |
| R2_BUCKET | `flooding-bucket` |
| R2_ENDPOINT | `https://1499f1ef89652b364430eff163d470bd.r2.cloudflarestorage.com/` |
| R2_ACCESS_KEY | `415dd75e0090418aa1d2362dd7191ad7` |
| R2_SECRET_KEY | (Ansible vault) |
| R2_PUBLIC_BASE_URL | `https://pub-2e450fd29a674f2ab950d5bcfab363cc.r2.dev/` |

---
