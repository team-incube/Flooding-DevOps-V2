# Flooding Infrastructure — 명령어 기록

> 모든 명령어는 실행 순서대로 기록되며, 각 명령의 목적과 결과를 설명합니다.

---

## 0. 사전 준비 (Control Node — macOS)

### sshpass 설치
```bash
brew install sshpass
```
> macOS에서 비밀번호 기반 SSH 자동화를 위해 필요. 초기 ssh-copy-id에만 사용.

### SSH 키 생성
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "ansible-control-flooding" -N ""
```
> Ansible이 사용할 Ed25519 키 쌍 생성. `-N ""`으로 passphrase 없이 생성.

### 전 노드 SSH 키 배포
```bash
SSHPASS="1234" sshpass -e ssh-copy-id \
  -o StrictHostKeyChecking=no \
  -i ~/.ssh/id_ed25519.pub \
  -p <PORT> ubuntu@gsmsv-1.yujun.kr
```
> 초기 비밀번호(`1234`)로 공개 키를 각 노드에 등록. 이후 키 인증만 사용.
> 대상 포트: 27101~27105 (gsmsv-1~5 순서)

### 노드 비밀번호 변경
```bash
ssh -i ~/.ssh/id_ed25519 -p <PORT> ubuntu@gsmsv-1.yujun.kr \
  "echo 'ubuntu:***REMOVED***' | sudo chpasswd"
```
> 키 인증 후 초기 비밀번호를 `***REMOVED***`으로 변경. 각 노드 반복 실행.

---

## 1. Ansible 디렉토리 구조 생성

```bash
mkdir -p ~/ansible/inventory/group_vars/all \
  ~/ansible/roles/{common,kubernetes,cilium,traefik,observability,harbor,argocd,langchain}/tasks \
  ~/ansible/roles/{traefik,langchain}/templates
```
> Ansible 표준 디렉토리 구조 생성.

---

## 2. ansible-vault 설정

### vault 비밀번호 파일 생성
```bash
echo 'flooding-infra-2026!' > ~/.ansible_vault_pass
chmod 600 ~/.ansible_vault_pass
```
> vault 암호화/복호화에 사용할 마스터 비밀번호 파일. 600 권한으로 보호.

### 시크릿 암호화 및 vault.yml 저장
```bash
ansible-vault encrypt_string '<값>' --name 'vault_<이름>' >> inventory/group_vars/all/vault.yml
```
> 저장된 시크릿 목록:
> - `vault_llm_api_key` — OpenAI API 키
> - `vault_grafana_admin_password` — Grafana admin 비밀번호
> - `vault_slack_webhook_url` — Slack Webhook URL
> - `vault_harbor_admin_password` — Harbor admin 비밀번호

### vault 변수 로드 확인
```bash
ansible -i inventory/hosts.ini gsmsv-1 -m debug \
  -a "msg={{ vault_grafana_admin_password }}"
```
> vault.yml이 `group_vars/all/` 하위에 있어야 all 그룹에 자동 로드됨.

---

## 3. 연결 확인

### Ansible ping 전체 노드
```bash
ansible all -i inventory/hosts.ini -m ping
```
> 모든 노드가 `pong` 응답해야 다음 단계 진행.

---

## 4. Layer 0 — Common

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags common
```
> 전체 노드에 공통 베이스라인 설정 (패키지, sysctl, containerd 등).

---

## 5. Layer 1 — Kubernetes

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags kubernetes
```
> 전체 노드에 kubeadm, kubelet, kubectl v1.29 설치.
> apt keyring 및 Kubernetes apt 저장소 추가 포함.

---

## 6. Layer 2 — Cilium CNI

### Helm 설치 (control-plane 노드)
```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```
> gsmsv-1(control-plane)에 Helm 3 설치. Cilium 이후 모든 Helm 배포에 사용.

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags cilium
```
> Cilium CNI를 Helm으로 설치. kube-proxy 대체 모드, Hubble 활성화.

---

## 7. StorageClass — local-path-provisioner

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.26/deploy/local-path-storage.yaml
kubectl patch storageclass local-path \
  -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```
> 베어메탈 환경에서 PVC 자동 프로비저닝을 위한 Rancher local-path-provisioner 설치.
> default StorageClass로 설정. Loki 등 PVC 필요 파드에 사용.

---

## 8. Layer 3 — Traefik Ingress

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags traefik
```
> Traefik v3.x를 Helm으로 설치. CRD 기반 IngressRoute 사용.

---

## 9. Layer 4 — Observability

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags observability
```
> 설치 목록:
> - `kube-prometheus-stack` — Prometheus + Grafana + Alertmanager
> - `loki-stack` — Loki + Promtail (전체 노드 로그 수집)

### Grafana NodePort 설정
```bash
kubectl patch svc kube-prometheus-stack-grafana -n monitoring \
  -p '{"spec":{"type":"NodePort","ports":[{"port":80,"targetPort":3000,"nodePort":30880}]}}'
```
> Grafana를 외부에서 접근 가능하도록 ClusterIP → NodePort(30880) 변경.

---

## 10. Layer 5 — Harbor (Private Registry)

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags harbor
```
> Harbor를 Helm으로 설치. NodePort 30104, externalURL: http://10.0.0.9:30880.
> persistence: local-path StorageClass 사용.

### Harbor flooding 프로젝트 생성
```bash
curl -s -X POST http://gsmsv-1.yujun.kr:28104/api/v2.0/projects \
  -u admin:***REMOVED*** \
  -H "Content-Type: application/json" \
  -d '{"project_name":"flooding","public":false}'
```
> CI/CD 파이프라인이 이미지를 push할 private 프로젝트 생성.

---

## 11. Layer 6 — ArgoCD (GitOps)

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags argocd
```
> ArgoCD를 Helm으로 설치. NodePort 30101(HTTP), 30443(HTTPS). TLS insecure 모드.

### ArgoCD Application 배포
```bash
kubectl apply -f argocd/flooding-server-app.yaml
```
> Flooding-DevOps-V2 레포를 소스로 하는 ArgoCD Application 생성.
> auto-sync, prune, selfHeal 활성화.

### ArgoCD admin 비밀번호 변경 (REST API)
```bash
# 토큰 발급
TOKEN=$(curl -s -X POST http://localhost:30101/api/v1/session \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<초기비밀번호>"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 비밀번호 변경
curl -s -X PUT http://localhost:30101/api/v1/account/password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"currentPassword":"<초기비밀번호>","newPassword":"***REMOVED***"}'
```
> argocd CLI TLS 프롬프트 우회를 위해 REST API 직접 호출.

---

## 12. 포트 포워딩 확인

물리 호스트에 설정된 DNAT 규칙:
```
28101 → 10.0.0.6:30101   (ArgoCD)
28104 → 10.0.0.9:30104   (Harbor)
28105 → 10.0.0.10:30880  (Grafana)
```

접속 확인:
```bash
curl -s http://gsmsv-1.yujun.kr:28101 -o /dev/null -w "%{http_code}"  # 200
curl -s http://gsmsv-1.yujun.kr:28104 -o /dev/null -w "%{http_code}"  # 200
curl -s http://gsmsv-1.yujun.kr:28105 -o /dev/null -w "%{http_code}"  # 302
```

---

## 13. Layer 7 — Infra Agent (LangChain Slack Bot)

### 소스 → 노드 전송 (macOS)
```bash
scp -P 27101 -r /Users/kimjihoon/Desktop/Flooding/langchain-agent \
  ubuntu@gsmsv-1.yujun.kr:/tmp/infra-agent
```
> 전체 langchain-agent 소스를 gsmsv-1 임시 디렉토리로 복사.

### 이미지 빌드 (gsmsv-1에서)
```bash
cd /tmp/infra-agent
sudo nerdctl --address /run/containerd/containerd.sock build \
  --insecure-registry \
  -t gsmsv-1.yujun.kr:28104/flooding/infra-agent:latest \
  .
```
> python:3.12-slim 기반 빌드. helm 바이너리 포함(helm_tool.py subprocess용).

### 이미지 Push (gsmsv-1에서)
```bash
sudo nerdctl --address /run/containerd/containerd.sock push \
  --insecure-registry \
  gsmsv-1.yujun.kr:28104/flooding/infra-agent:latest
```
> Harbor HTTP(insecure) 레지스트리에 Push.

### infra-agent-secret 생성 (gsmsv-1에서)
```bash
kubectl create secret generic infra-agent-secret \
  --from-literal=OPENAI_API_KEY=<key> \
  --from-literal=SLACK_BOT_TOKEN=<xoxb-...> \
  --from-literal=SLACK_APP_TOKEN=<xapp-...> \
  --from-literal=SLACK_SIGNING_SECRET=<secret> \
  --from-literal=SLACK_ALERT_CHANNEL='#infra-alerts' \
  --from-literal=OPENAI_MODEL=gpt-4o \
  --from-literal=PROMETHEUS_URL=http://kube-prometheus-stack-prometheus.monitoring.svc:9090 \
  --from-literal=LOKI_URL=http://loki-stack.monitoring.svc:3100 \
  -n flooding
```
> Slack Bolt + LangChain에 필요한 모든 환경변수를 Secret으로 관리.

### harbor-pull-secret 생성 (gsmsv-1에서)
```bash
kubectl create secret docker-registry harbor-pull-secret \
  --docker-server=gsmsv-1.yujun.kr:28104 \
  --docker-username=admin \
  --docker-password=***REMOVED*** \
  -n flooding
```
> Private Harbor 레지스트리 인증. ImagePullBackOff 방지.

### 배포 (gsmsv-1에서)
```bash
kubectl apply -f /tmp/infra-agent/k8s/deployment.yaml
kubectl rollout status deployment/infra-agent -n flooding --timeout=300s
```
> ServiceAccount, ClusterRole, ClusterRoleBinding, Deployment, Service(NodePort 30200) 일괄 적용.

### 배포 재시작 (이미지 갱신 후)
```bash
kubectl rollout restart deployment/infra-agent -n flooding
kubectl rollout status deployment/infra-agent -n flooding
```

### 빌드+푸시+배포 한번에 (macOS 로컬 스크립트)
```bash
bash langchain-agent/scripts/deploy.sh
```
> rsync로 소스 전송 → nerdctl 빌드 → Push → rollout restart 자동화.

### 로그 확인
```bash
kubectl logs -n flooding -l app=infra-agent --tail=50 -f
```

---

## 14. Alertmanager → infra-agent 웹훅 연동

### Alertmanager 재설정 (Ansible)
```bash
# macOS에서
ansible-playbook site.yml -i inventory/hosts.ini --tags observability
```
> `--reuse-values -f alertmanager-values.yml`로 기존 설치에 웹훅 설정 추가.
> Alertmanager가 infra-agent로 알림 전달:
>   http://infra-agent.flooding.svc/webhook/alertmanager

### 물리 서버 관리자 요청 — infra-agent 외부 포트 오픈
```
28106 → 10.0.0.6:30200  (infra-agent NodePort)
```
> Alertmanager 웹훅은 클러스터 내부에서 ClusterDNS로 접근하므로 외부 포트 불필요.
> (외부에서 직접 테스트할 때만 필요)

---

## 15. httpx 버전 고정 (proxies 에러 수정)

### 원인
`httpx 0.28.x`가 `proxies` 파라미터를 제거하여 `langchain-openai 0.1.25`와 충돌.

### 수정
`langchain-agent/requirements.txt`에 `httpx==0.27.2` 추가.
이미지 재빌드 후 배포.

---

## 서비스 접속 정보

| 서비스 | URL | ID | PW |
|---|---|---|---|
| ArgoCD | http://gsmsv-1.yujun.kr:28101 | admin | ***REMOVED*** |
| Harbor | http://gsmsv-1.yujun.kr:28104 | admin | ***REMOVED*** |
| Grafana | http://gsmsv-1.yujun.kr:28105 | admin | ***REMOVED*** |
| Infra Agent | (클러스터 내부) flooding.infra-agent.svc:80 | — | — |

---

## 클러스터 노드 정보

| 노드 | SSH | 내부 IP | 역할 |
|---|---|---|---|
| gsmsv-1 | 27101 | 10.0.0.6 | control-plane |
| gsmsv-2 | 27102 | 10.0.0.7 | worker |
| gsmsv-3 | 27103 | 10.0.0.8 | worker |
| gsmsv-4 | 27104 | 10.0.0.9 | worker/storage |
| gsmsv-5 | 27105 | 10.0.0.10 | monitoring |
