# Flooding Infra — 실행 명령어 기록

> 이 파일은 인프라 자동화 과정에서 실행된 모든 명령어를 설명과 함께 기록합니다.
> 최종 업데이트: 2026-03-18

---

## 0. 사전 준비 — 디렉토리 구조 생성

```bash
mkdir -p ~/ansible/inventory/group_vars \
  ~/ansible/roles/common/tasks \
  ~/ansible/roles/kubernetes/tasks \
  ~/ansible/roles/cilium/tasks \
  ~/ansible/roles/traefik/tasks \
  ~/ansible/roles/traefik/templates \
  ~/ansible/roles/observability/tasks \
  ~/ansible/roles/langchain/tasks \
  ~/ansible/roles/langchain/templates
```
> Ansible 프로젝트 표준 디렉토리 구조 생성.
> `roles/<name>/tasks/` — 각 레이어 태스크 파일 위치
> `roles/<name>/templates/` — Jinja2 템플릿(K8s manifest 등) 위치

---

## 1. SSH 초기 접속 설정

### 1-1. sshpass 설치

```bash
brew install sshpass
```
> macOS에서 비밀번호 기반 SSH 자동화 도구 설치.
> `ssh-copy-id`에 비밀번호를 인자로 넘기기 위해 필요.

### 1-2. Ed25519 SSH 키 쌍 생성

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "ansible-control-flooding" -N ""
```
> 컨트롤 노드에서 사용할 SSH 키 쌍 생성.
> `-t ed25519` — 현재 권장되는 타원곡선 알고리즘 (RSA보다 빠르고 안전)
> `-N ""` — passphrase 없이 생성 (Ansible 자동화를 위해 필요)
> `-C` — 키 식별용 코멘트

### 1-3. 전체 노드에 공개키 배포

```bash
SSHPASS="<초기비밀번호>" sshpass -e ssh-copy-id \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=10 \
  -i ~/.ssh/id_ed25519.pub \
  -p <PORT> ubuntu@gsmsv-1.yujun.kr
```
> `sshpass -e` — 환경변수 `SSHPASS`에서 비밀번호를 읽음 (명령행 노출 방지)
> `StrictHostKeyChecking=no` — 최초 접속 시 호스트 키 자동 수락
> 노드별 포트: gsmsv-1=27101, gsmsv-2=27102, gsmsv-3=27103, gsmsv-4=27104, gsmsv-5=27105

### 1-4. 키 기반 접속 검증

```bash
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
  -i ~/.ssh/id_ed25519 \
  -p <PORT> ubuntu@gsmsv-1.yujun.kr "echo pong"
```
> 비밀번호 없이 키로만 접속되는지 확인.
> 각 노드에서 `pong` 응답이 오면 키 배포 성공.

### 1-5. 비밀번호 변경

```bash
ssh -i ~/.ssh/id_ed25519 -p <PORT> ubuntu@gsmsv-1.yujun.kr \
  "echo 'ubuntu:<새비밀번호>' | sudo chpasswd"
```
> `chpasswd` — stdin에서 `user:password` 형식으로 읽어 비밀번호 일괄 변경.
> `sudo` 권한으로 실행하여 ubuntu 계정 비밀번호 변경.
> **실행 결과: 5개 노드 모두 SUCCESS**

---

## 2. Ansible 설치

```bash
pip3 install --break-system-packages ansible
```
> 컨트롤 노드(macOS)에 Ansible 설치.
> `--break-system-packages` — macOS 시스템 Python 보호 경고 우회 (Homebrew 환경)
> 설치된 버전: ansible-13.4.0 / ansible-core-2.20.3

---

## 3. Ansible Vault 설정

### 3-1. Vault 패스워드 파일 생성

```bash
printf '%s' '<vault패스워드>' > ~/.ansible_vault_pass
chmod 600 ~/.ansible_vault_pass
```
> Vault 마스터 비밀번호를 홈 디렉토리에 저장 (프로젝트 디렉토리 외부).
> `chmod 600` — 본인만 읽기/쓰기 가능하도록 권한 제한.
> `printf '%s'` — `echo` 대신 사용하여 불필요한 개행 문자 방지.
> `ansible.cfg`의 `vault_password_file = ~/.ansible_vault_pass`로 참조.

### 3-2. LLM API 키 암호화

```bash
ansible-vault encrypt_string '<API_KEY>' --name 'vault_llm_api_key'
```
> API 키를 AES256으로 암호화하여 YAML 형식의 vault 변수로 출력.
> 출력 결과를 `inventory/group_vars/vault.yml`에 저장.
> Playbook에서 `{{ vault_llm_api_key }}`로 참조하면 자동 복호화됨.

---

## 4. Ansible Ping 검증

```bash
ansible all -i inventory/hosts.ini -m ping --private-key ~/.ssh/id_ed25519
```
> 인벤토리의 전체 노드에 Ansible ping 모듈 실행.
> `-m ping` — Python이 실행 가능한지, SSH 접속이 되는지 확인 (ICMP ping 아님)
> 모든 노드에서 `"ping": "pong"` 응답 확인.
> **결과: 5/5 SUCCESS**

---

## 5. 프로비저닝 (진행 예정)

### Layer 0 — common (드라이런)

```bash
cd ~/ansible
ansible-playbook site.yml -i inventory/hosts.ini --tags common --check
```
> `--check` — 실제 변경 없이 무엇이 바뀌는지 시뮬레이션 (드라이런).
> `--tags common` — common 롤만 선택적으로 실행.

### Layer 0 — common (실제 실행)

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags common
```
> 드라이런 확인 후 실제 프로비저닝 실행.

### Layer 1 — kubernetes

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags kubernetes
```

### Layer 2 — cilium

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags cilium
```

### Layer 3 — traefik

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags traefik
```

### Layer 4 — observability

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags observability
```

### Layer 5 — langchain

```bash
ansible-playbook site.yml -i inventory/hosts.ini --tags langchain
```

---

## 6. 유용한 운영 명령어

### 특정 노드만 실행

```bash
ansible-playbook site.yml -i inventory/hosts.ini --limit gsmsv-1 --tags common
```
> `--limit` — 특정 노드 또는 그룹만 대상으로 지정.

### vault 내용 확인

```bash
ansible-vault view inventory/group_vars/vault.yml
```

### vault 내용 편집

```bash
ansible-vault edit inventory/group_vars/vault.yml
```

### 새 vault 변수 추가

```bash
ansible-vault encrypt_string '<값>' --name 'vault_<이름>'
```
> 출력 결과를 `inventory/group_vars/vault.yml`에 추가.

### kubectl — 노드 상태 확인 (클러스터 구성 후)

```bash
ssh -i ~/.ssh/id_ed25519 -p 27101 ubuntu@gsmsv-1.yujun.kr "kubectl get nodes -o wide"
```

### Helm 릴리스 목록 확인 (클러스터 구성 후)

```bash
ssh -i ~/.ssh/id_ed25519 -p 27101 ubuntu@gsmsv-1.yujun.kr "helm list -A"
```

---

## 파일 구조 요약

```
~/.ssh/id_ed25519          — SSH 프라이빗 키 (컨트롤 노드)
~/.ansible_vault_pass      — Vault 마스터 비밀번호 (chmod 600)

~/ansible/
├── ansible.cfg                          — Ansible 설정 (키 경로, vault 파일 경로)
├── site.yml                             — 마스터 플레이북 (L0~L5 순서 실행)
├── inventory/
│   ├── hosts.ini                        — 노드 인벤토리 (IP, 포트, 유저)
│   └── group_vars/
│       ├── all.yml                      — 공통 변수 (버전, 네임스페이스 등)
│       └── vault.yml                    — AES256 암호화된 시크릿
└── roles/
    ├── common/tasks/main.yml            — L0: OS 기본 설정, containerd
    ├── kubernetes/tasks/main.yml        — L1: kubeadm, kubelet, kubectl
    ├── cilium/tasks/main.yml            — L2: Cilium CNI (Helm)
    ├── traefik/tasks/main.yml           — L3: Traefik Ingress (Helm)
    ├── observability/tasks/main.yml     — L4: Prometheus + Loki + Grafana
    └── langchain/tasks/main.yml         — L5: LangChain Agent pods
```
