# Flooding Infra Agent — 기술 문서

> 이 문서는 Flooding 학교 관리 서비스의 Kubernetes 인프라를 자동으로 모니터링·운영하는 AI 에이전트(`infra-agent`)의 전체 아키텍처와 설계 결정을 설명합니다. 유지보수 및 후임 담당자를 위한 문서입니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [전체 아키텍처](#2-전체-아키텍처)
3. [디렉토리 구조](#3-디렉토리-구조)
4. [핵심 컴포넌트 상세](#4-핵심-컴포넌트-상세)
   - 4.1 [진입점 (main.py)](#41-진입점-mainpy)
   - 4.2 [에이전트 오케스트레이터 (agent/orchestrator.py)](#42-에이전트-오케스트레이터-agentorchestratorpy)
   - 4.3 [시스템 프롬프트 (agent/prompts.py)](#43-시스템-프롬프트-agentpromptspy)
   - 4.4 [메모리 (agent/memory.py)](#44-메모리-agentmemorypy)
5. [LangChain 설계 상세](#5-langchain-설계-상세)
   - 5.1 [에이전트 타입 선택 이유](#51-에이전트-타입-선택-이유)
   - 5.2 [툴 설계 원칙](#52-툴-설계-원칙)
   - 5.3 [승인(Approval) 패턴](#53-승인approval-패턴)
   - 5.4 [Output 보강 로직](#54-output-보강-로직)
6. [툴 상세 명세](#6-툴-상세-명세)
   - 6.1 [kubectl 툴](#61-kubectl-툴)
   - 6.2 [Prometheus 툴](#62-prometheus-툴)
   - 6.3 [Loki 툴](#63-loki-툴)
   - 6.4 [Helm 툴](#64-helm-툴)
   - 6.5 [Runbook 툴](#65-runbook-툴)
7. [핸들러 상세](#7-핸들러-상세)
   - 7.1 [Slack 메시지 핸들러](#71-slack-메시지-핸들러)
   - 7.2 [승인 핸들러](#72-승인-핸들러)
   - 7.3 [Alert 핸들러](#73-alert-핸들러)
8. [전체 요청 흐름](#8-전체-요청-흐름)
   - 8.1 [일반 조회 흐름](#81-일반-조회-흐름)
   - 8.2 [파괴적 작업(승인 필요) 흐름](#82-파괴적-작업승인-필요-흐름)
   - 8.3 [Alertmanager 알람 흐름](#83-alertmanager-알람-흐름)
9. [인프라 구성 (Kubernetes)](#9-인프라-구성-kubernetes)
10. [환경 변수 및 시크릿](#10-환경-변수-및-시크릿)
11. [배포 방법](#11-배포-방법)
12. [Runbook 구조 및 추가 방법](#12-runbook-구조-및-추가-방법)
13. [알려진 제약사항 및 설계 결정 배경](#13-알려진-제약사항-및-설계-결정-배경)
14. [트러블슈팅 가이드](#14-트러블슈팅-가이드)

---

## 1. 프로젝트 개요

`infra-agent`는 Slack을 인터페이스로 사용하는 Kubernetes 인프라 운영 자동화 AI 에이전트입니다.

### 주요 기능

| 기능 | 설명 |
|------|------|
| **인프라 상태 조회** | Pod 상태, 노드 리소스, K8s 이벤트 실시간 확인 |
| **메트릭 분석** | Prometheus PromQL로 CPU/메모리/에러율 조회 |
| **로그 분석** | Loki LogQL로 에러 로그 집계 및 분석 |
| **Helm 관리** | 릴리스 히스토리 조회 및 롤백 요청 |
| **장애 진단** | 여러 소스(메트릭+로그+이벤트)를 조합한 근본 원인 분석 |
| **승인 기반 작업** | Scale/Restart/Rollback은 Slack 버튼 승인 후 실행 |
| **알람 자동 분석** | Alertmanager 웹훅 수신 → 자동 분석 결과 Slack 전송 |

### 기술 스택

- **LangChain** 0.2.16 + **OpenAI** GPT-4o: AI 에이전트 프레임워크
- **Slack Bolt** (Socket Mode): Slack 이벤트 처리
- **FastAPI** + **uvicorn**: HTTP 웹훅 서버
- **kubernetes-python**: K8s API 클라이언트
- **Prometheus HTTP API**: 메트릭 쿼리
- **Loki HTTP API**: 로그 쿼리
- **Helm CLI** (subprocess): 릴리스 관리

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                          Slack                                   │
│  사용자 멘션 (@infra-agent ...)    승인 버튼 클릭 (Approve/Reject) │
└───────────────┬─────────────────────────────┬───────────────────┘
                │ Socket Mode                  │ Action Payload
                ▼                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    main.py  (Slack Bolt + FastAPI)               │
│                                                                  │
│  bolt_app (AsyncApp)          api (FastAPI)                      │
│  ├─ message_handler           └─ alert_handler (POST /webhook)   │
│  └─ approval_handler                                             │
└───────────────┬──────────────────────────────────────────────────┘
                │ run_agent()
                ▼
┌──────────────────────────────────────────────────────────────────┐
│                   LangChain Agent (orchestrator.py)              │
│                                                                  │
│  create_openai_tools_agent                                       │
│  ├─ ChatOpenAI (gpt-4o)                                          │
│  ├─ SystemMessage (SYSTEM_PROMPT)                                │
│  ├─ ConversationBufferWindowMemory (per-channel, k=10)           │
│  └─ AgentExecutor (max_iterations=15)                            │
└───────────────┬──────────────────────────────────────────────────┘
                │ tool calls (native function calling)
                ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Tools (15개)                             │
│                                                                  │
│  kubectl         Prometheus       Loki           Helm            │
│  ├─ get_pod_status  ├─ query_metric  ├─ query_logs  ├─ get_release_history │
│  ├─ get_node_status ├─ get_alerts    └─ get_error_logs └─ rollback_release  │
│  ├─ get_events      └─ get_service_error_rate     └─ get_current_values    │
│  ├─ describe_pod                                                 │
│  ├─ scale_deployment ──────────────────────────┐                 │
│  └─ restart_deployment ─────────────────────┐  │  Runbook        │
│                                             │  │  └─ match_runbook│
│                                             ▼  ▼                 │
│                              <APPROVAL_REQUEST> 블록 반환         │
└──────────────────────────────────────────────────────────────────┘
                │ approval request
                ▼
┌──────────────────────────────────────────────────────────────────┐
│              approval_handler.py                                 │
│  pending_approvals (in-memory dict, 120s TTL)                    │
│  Approve → execute_scale_deployment / execute_restart / rollback │
│  Reject  → 취소 메시지                                            │
└──────────────────────────────────────────────────────────────────┘
                │ Kubernetes API / Helm CLI
                ▼
┌──────────────────────────────────────────────────────────────────┐
│              Flooding Kubernetes Cluster (bare-metal)            │
│  flooding-1 (10.0.0.6) control-plane                            │
│  flooding-2 (10.0.0.7) worker                                   │
│  flooding-3 (10.0.0.8) worker                                   │
│  flooding-4 (10.0.0.9) worker/storage                           │
│  flooding-5 (10.0.0.10) monitoring (Prometheus, Loki, Grafana)  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 디렉토리 구조

```
langchain-agent/
├── main.py                    # 진입점: Slack Bolt + FastAPI 동시 실행
├── config.py                  # 환경변수 로드
├── requirements.txt           # Python 의존성
├── Dockerfile                 # 컨테이너 빌드
│
├── agent/
│   ├── orchestrator.py        # LangChain 에이전트 빌드 및 싱글턴 관리
│   ├── prompts.py             # 시스템 프롬프트
│   └── memory.py              # 채널별 대화 메모리
│
├── handlers/
│   ├── message_handler.py     # Slack @mention 처리
│   ├── approval_handler.py    # 승인/거절 버튼 처리 + 실행
│   └── alert_handler.py       # Alertmanager 웹훅 수신
│
├── tools/
│   ├── kubectl_tool.py        # Kubernetes API 툴
│   ├── prometheus_tool.py     # Prometheus HTTP API 툴
│   ├── loki_tool.py           # Loki HTTP API 툴
│   ├── helm_tool.py           # Helm CLI subprocess 툴
│   └── runbook_tool.py        # YAML 런북 매칭 툴
│
├── formatters/
│   └── slack_formatter.py     # Slack Block Kit 메시지 포맷터
│
├── runbooks/
│   └── runbook.yaml           # 장애 유형별 진단 가이드
│
├── k8s/
│   ├── deployment.yaml        # K8s Deployment + RBAC
│   └── secret.yaml            # 시크릿 템플릿
│
└── scripts/
    └── deploy.sh              # 로컬 → gsmsv-1 빌드/배포 스크립트
```

---

## 4. 핵심 컴포넌트 상세

### 4.1 진입점 (main.py)

두 개의 비동기 서버를 동시에 실행합니다.

```python
await asyncio.gather(
    socket_handler.start_async(),   # Slack Socket Mode
    server.serve(),                 # FastAPI (uvicorn)
)
```

#### `run_agent()` 함수

```python
async def run_agent(text: str, channel_id: str = "default", memory=None) -> dict:
```

- LangChain `AgentExecutor.invoke()`는 동기(sync) 함수 → `run_in_executor`로 스레드풀에서 실행
- `agent.invoke()` 호출 시 `input`(사용자 텍스트)과 `chat_history`(채널 메모리)를 전달
- 실행 완료 후 `_enrich_output()`으로 응답 보완
- `mem.save_context()`로 대화 기록 저장

#### `_enrich_output()` 함수

LLM이 부실한 응답을 반환할 때를 처리합니다.

```python
_ITERATION_LIMIT_MSG = "agent stopped due to iteration limit or time limit"
_VAGUE_PHRASES = ("provided above", "shown above", "listed above", ...)
```

| 상황 | 처리 방식 |
|------|-----------|
| Iteration 한도 도달 | 마지막으로 수집한 툴 결과를 응답에 포함 |
| "provided above" 같은 모호한 표현 | 실제 툴 결과로 교체 |

---

### 4.2 에이전트 오케스트레이터 (agent/orchestrator.py)

#### 에이전트 구성

```python
def build_agent() -> AgentExecutor:
    llm = ChatOpenAI(model=cfg.OPENAI_MODEL, temperature=0, ...)

    # SystemMessage 사용: SYSTEM_PROMPT 내 {중괄호}가 템플릿 변수로
    # 오해되는 것을 방지 (PromQL의 {namespace=...} 등)
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history", optional=True),
        HumanMessagePromptTemplate.from_template("{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm=llm, tools=ALL_TOOLS, prompt=prompt)

    executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=15,
        verbose=True,
        return_intermediate_steps=True,  # 승인 요청 탐지에 필요
    )
```

**싱글턴 패턴**: `_agent` 전역 변수로 한 번만 빌드하고 재사용합니다. 에이전트 빌드 시 LangChain Hub 접근이나 모델 초기화가 발생하므로 재사용이 중요합니다.

---

### 4.3 시스템 프롬프트 (agent/prompts.py)

프롬프트는 에이전트의 행동 방침을 정의합니다. 핵심 지침:

1. **역할 정의**: Flooding K8s 클러스터의 인프라 운영 어시스턴트
2. **클러스터 토폴로지**: 5개 노드 IP/역할 명시
3. **핵심 네임스페이스**: flooding, monitoring, traefik, harbor, argocd
4. **파괴적 작업 규칙**: scale/restart/rollback은 반드시 해당 툴을 호출해 승인 요청 생성
5. **최종 응답 규칙**: "provided above" 같은 모호한 표현 금지, 실제 숫자/데이터 포함 필수
6. **툴 사용 규칙**:
   - CPU: `sum(rate(container_cpu_usage_seconds_total{{...}}[5m])) by (pod)` 형태 고정
   - Memory: `sum(container_memory_working_set_bytes{{...}}) by (pod)` 형태 고정
   - K8s 이벤트는 참고용, 메트릭 대체 불가

> **주의**: 프롬프트에서 `{변수명}` 형태는 `ChatPromptTemplate`이 템플릿 변수로 인식합니다.
> PromQL의 레이블 선택자 `{namespace="..."}` 는 반드시 `{{namespace="..."}}` 로 이중 이스케이프해야 합니다.
> 그러나 더 근본적인 해결책으로 `orchestrator.py`에서 `SystemMessage(content=SYSTEM_PROMPT)` 객체를 사용하면 파싱 자체가 일어나지 않습니다.

---

### 4.4 메모리 (agent/memory.py)

```python
# 채널별 독립 메모리 (Slack 채널 ID를 키로 사용)
_memory_store: dict[str, ConversationBufferWindowMemory] = {}

def get_memory(channel_id: str) -> ConversationBufferWindowMemory:
    if channel_id not in _memory_store:
        _memory_store[channel_id] = ConversationBufferWindowMemory(
            k=10,                          # 최근 10턴 유지
            memory_key="chat_history",
            return_messages=True,
        )
    return _memory_store[channel_id]
```

- 재시작 시 메모리 초기화됨 (in-memory only, Redis 등 외부 저장소 미사용)
- 채널마다 독립적 컨텍스트 유지 (DM vs 채널 구분)

---

## 5. LangChain 설계 상세

### 5.1 에이전트 타입 선택 이유

#### ReAct 에이전트 (구 버전, 현재 미사용)

```python
# 이전 방식 - 텍스트 파싱 기반
agent = create_react_agent(llm=llm, tools=ALL_TOOLS, prompt=hub.pull("hwchase17/react"))
```

**문제점**:
- LLM 출력을 텍스트로 파싱 → `Thought:` 다음에 `Action:` 누락 시 파싱 에러
- 파싱 에러가 iteration을 소모 → 반복되면 iteration 한도 초과
- Action Input이 항상 **문자열**로 전달 → multi-arg 툴의 첫 번째 파라미터에 전체 문자열이 들어감 (나머지 파라미터는 기본값으로 세팅되는 버그)

#### OpenAI Tools 에이전트 (현재 방식)

```python
# 현재 방식 - Native Function Calling
agent = create_openai_tools_agent(llm=llm, tools=ALL_TOOLS, prompt=prompt)
```

**장점**:
- OpenAI의 native function calling API 사용 → 파싱 에러 없음
- 툴 파라미터가 JSON 스키마로 정확히 전달
- LangChain이 Pydantic 모델로 자동 검증

---

### 5.2 툴 설계 원칙

#### 단순 조회 툴: 결과를 문자열로 반환

```python
@tool
def get_pod_status(namespace: str = "default") -> str:
    """List all pods in a namespace..."""
    # Kubernetes API 호출 → 텍스트 테이블 반환
    return "\n".join(lines)
```

#### 파괴적 작업 툴: `<APPROVAL_REQUEST>` 블록 반환

```python
@tool
def scale_deployment(name: str, replicas: int, namespace: str = "flooding") -> str:
    """Scale a Kubernetes deployment... REQUIRES APPROVAL."""
    approval = {
        "action": "scale_deployment",
        "description": f"Scale '{name}' to {replicas} replicas",
        "params": {"name": name, "namespace": namespace, "replicas": replicas},
        "reason": "...",
    }
    return f"<APPROVAL_REQUEST>\n{json.dumps(approval, indent=2)}\n</APPROVAL_REQUEST>"
```

**왜 Exception 대신 문자열 반환?**

초기에는 `RequiresApprovalError` 예외를 raise했습니다. 그러나:
- LangChain의 `BaseTool.run()`이 예외를 잡아서 error observation으로 변환할 수 있음
- LLM이 에러 메시지를 보고 "승인 필요"라는 텍스트만 출력하고 실제 JSON 블록을 생성하지 않음
- 결과적으로 Slack 버튼이 나타나지 않는 문제 발생

문자열로 반환하면:
- LangChain이 이를 정상 tool result로 처리
- LLM이 Final Answer에 이 내용을 포함하거나 intermediate_steps에 저장됨
- `message_handler.py`가 두 경로(최종 응답 + 중간 스텝)에서 블록을 탐지

---

### 5.3 승인(Approval) 패턴

#### 전체 흐름

```
1. LLM → scale_deployment(name="flooding-server", replicas=4, namespace="flooding") 호출
2. 툴 → <APPROVAL_REQUEST> JSON 블록 반환
3. LLM → Final Answer에 블록 포함 (또는 intermediate_steps에 존재)
4. message_handler → _extract_approval() 로 블록 파싱
   - 먼저 Final Answer에서 탐색
   - 없으면 intermediate_steps 순회
5. format_approval_request() → Slack Block Kit 버튼 메시지 생성
6. create_approval_request() → UUID 생성, pending_approvals 딕셔너리에 저장
7. 사용자 클릭 → approval_handler.handle_approve() or handle_reject()
8. handle_approve() → _is_expired() 확인 (120초) → _execute_action() 실행
```

#### 승인 요청 데이터 구조

```python
@dataclass
class ApprovalRequest:
    request_id: str          # UUID
    action: str              # "scale_deployment" | "restart_deployment" | "helm_rollback"
    params: dict             # 실행에 필요한 파라미터
    description: str         # 사람이 읽을 수 있는 설명
    reason: str              # 에이전트가 판단한 이유
    channel: str             # Slack 채널 ID
    message_ts: str          # 원본 메시지 타임스탬프
    created_at: datetime     # 생성 시각 (TTL 계산용)
```

#### 지원 액션

| 액션 | 실행 함수 | 파라미터 |
|------|-----------|----------|
| `scale_deployment` | `execute_scale_deployment(name, namespace, replicas)` | Kubernetes API patch |
| `restart_deployment` | `execute_restart_deployment(name, namespace)` | 어노테이션 패치로 rolling restart |
| `helm_rollback` | `execute_rollback(release, namespace, revision)` | `helm rollback` subprocess |

---

### 5.4 Output 보강 로직

`main.py`의 `_enrich_output()` 함수가 두 가지 케이스를 처리합니다.

**케이스 1: Iteration 한도 도달**

```python
if _ITERATION_LIMIT_MSG in output.lower():
    # intermediate_steps에서 마지막으로 성공한 툴 결과 추출
    useful = [(action, obs) for action, obs in steps if len(obs) > 10]
    if useful:
        action, obs = useful[-1]
        result["output"] = f"분석 중 반복 한도에 도달했습니다. 마지막으로 수집한 정보:\n\n*{action.tool}*\n```\n{obs}\n```"
```

**케이스 2: 모호한 표현**

```python
_VAGUE_PHRASES = ("provided above", "shown above", "listed above", ...)
if any(p in output.lower() for p in _VAGUE_PHRASES):
    # 모든 툴 결과를 조합해 응답 교체
    result["output"] = "\n\n".join([f"*{action.tool}*\n```\n{obs}\n```" for ...])
```

---

## 6. 툴 상세 명세

### 6.1 kubectl 툴

**파일**: `tools/kubectl_tool.py`

kubeconfig 로딩 순서:
1. In-cluster config (`/var/run/secrets/kubernetes.io/serviceaccount/token`)
2. 실패 시 파일 (`KUBECONFIG_PATH` 환경변수 또는 `~/.kube/config`)

| 툴 이름 | 파라미터 | 설명 |
|---------|---------|------|
| `get_pod_status` | `namespace: str = "default"` | 네임스페이스의 모든 Pod 상태/재시작/경과시간 |
| `get_node_status` | `label_selector: str = ""` | 노드 CPU/메모리 할당 가능 용량 |
| `get_events` | `namespace: str`, `limit: int = 20` | Warning 이벤트 최신순 |
| `describe_pod` | `pod_name: str`, `namespace: str = "default"` | Pod 상세 (조건, 컨테이너 상태, 이벤트) |
| `scale_deployment` | `name: str`, `replicas: int`, `namespace: str = "flooding"` | 승인 요청 생성 |
| `restart_deployment` | `name: str`, `namespace: str = "flooding"` | 승인 요청 생성 |

**실행 함수** (승인 후 approval_handler에서 호출):

```python
def execute_scale_deployment(name: str, namespace: str, replicas: int) -> str:
    apps = client.AppsV1Api()
    apps.patch_namespaced_deployment_scale(name, namespace, {"spec": {"replicas": replicas}})

def execute_restart_deployment(name: str, namespace: str) -> str:
    # kubectl.kubernetes.io/restartedAt 어노테이션 추가 → K8s가 rolling restart 트리거
    now = datetime.now(timezone.utc).isoformat()
    body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}
    apps.patch_namespaced_deployment(name, namespace, body)
```

---

### 6.2 Prometheus 툴

**파일**: `tools/prometheus_tool.py`

모든 쿼리는 `{PROMETHEUS_URL}/api/v1/query` 엔드포인트를 사용합니다. (기본값: `http://prometheus-service.monitoring:9090`)

| 툴 이름 | 파라미터 | 설명 |
|---------|---------|------|
| `query_metric` | `promql: str` | PromQL 쿼리 실행, 최대 20개 결과 반환 |
| `get_alerts` | `filter_labels: str = ""` | Alertmanager에서 현재 firing 알람 조회 |
| `get_service_error_rate` | `service: str`, `duration: str = "5m"` | HTTP 5xx 에러율 계산 |

**쿼리 응답 처리**:
- `resultType == "scalar"`: 단일 값 반환
- `resultType == "vector"`: `metric_labels: value` 형태로 최대 20행
- 빈 결과: "No data returned for query: ..." 반환

**에러율 상태 분류**:
```python
status = "CRITICAL" if pct > 5 else "WARNING" if pct > 1 else "OK"
```

---

### 6.3 Loki 툴

**파일**: `tools/loki_tool.py`

`{LOKI_URL}/loki/api/v1/query_range` 엔드포인트를 사용합니다. (기본값: `http://loki.monitoring:3100`)

| 툴 이름 | 파라미터 | 설명 |
|---------|---------|------|
| `query_logs` | `logql: str`, `limit: int = 50`, `duration: str = "1h"` | LogQL 쿼리 실행 |
| `get_error_logs` | `namespace: str`, `duration: str = "30m"` | ERROR/EXCEPTION/FATAL 로그 집계 |

**`get_error_logs` 동작**:
1. `{job=~".+", namespace="<ns>"}` 로 해당 네임스페이스 전체 로그 조회
2. ERROR, EXCEPTION, FATAL 키워드 필터링
3. 중복 메시지 집계 (Counter)
4. 상위 10개 에러를 빈도순으로 반환

---

### 6.4 Helm 툴

**파일**: `tools/helm_tool.py`

Helm CLI를 subprocess로 실행합니다 (타임아웃 60초).

| 툴 이름 | 파라미터 | 설명 |
|---------|---------|------|
| `get_release_history` | `release: str`, `namespace: str` | 릴리스 히스토리 최대 10개 |
| `rollback_release` | `release: str`, `namespace: str`, `revision: int = 0` | 승인 요청 생성 (revision=0은 이전 버전) |
| `get_current_values` | `release: str`, `namespace: str` | 현재 배포된 Helm values |

**실행 함수** (승인 후):
```python
def execute_rollback(release: str, namespace: str, revision: int = 0) -> str:
    # helm rollback <release> <revision> -n <namespace> --wait
```

---

### 6.5 Runbook 툴

**파일**: `tools/runbook_tool.py`

| 툴 이름 | 파라미터 | 설명 |
|---------|---------|------|
| `match_runbook` | `symptom: str` | 증상 키워드로 런북 패턴 매칭 |

**런북 구조** (`runbooks/runbook.yaml`):

```yaml
runbooks:
  - id: crashloop
    patterns: ["CrashLoopBackOff", "crash", "crashloop"]
    diagnosis:
      - "check logs: kubectl logs <pod> -n <namespace> --previous"
      - "check resource limits"
    actions:
      - type: approval_required
        tool: restart_deployment
      - type: auto
        tool: describe_pod
```

**매칭 로직**: 증상 문자열을 소문자로 변환 후 각 패턴과 `in` 비교. 첫 번째 매칭 런북 반환.

---

## 7. 핸들러 상세

### 7.1 Slack 메시지 핸들러

**파일**: `handlers/message_handler.py`

```python
@app.event("app_mention")
async def handle_mention(event, say, client):
    # 1. 봇 멘션 제거: "<@U12345> 텍스트" → "텍스트"
    user_text = _strip_mention(event.get("text", ""))

    # 2. :thinking_face: 이모지 추가 (처리 중 표시)
    await client.reactions_add(channel=channel, timestamp=ts, name="thinking_face")

    # 3. 에이전트 실행
    result = await agent_fn(user_text, channel_id=channel, memory=memory)

    # 4. <APPROVAL_REQUEST> 블록 추출 (Final Answer → intermediate_steps 순서)
    clean_text, approval = _extract_approval(output)
    if not approval:
        for _action, observation in result.get("intermediate_steps", []):
            _, approval = _extract_approval(observation)
            if approval: break

    # 5. 응답 전송
    await client.chat_postMessage(channel=channel, **format_agent_response(clean_text))
    if approval:
        await client.chat_postMessage(channel=channel, **format_approval_request(...))

    # 6. :thinking_face: 이모지 제거
```

**`_extract_approval()` 함수**:

```python
_APPROVAL_RE = re.compile(r"<APPROVAL_REQUEST>\s*(\{.*?\})\s*</APPROVAL_REQUEST>", re.DOTALL)

def _extract_approval(text: str) -> tuple[str, dict | None]:
    match = _APPROVAL_RE.search(text)
    if not match: return text, None
    approval = json.loads(match.group(1))
    clean = _APPROVAL_RE.sub("", text).strip()  # 블록을 응답 텍스트에서 제거
    return clean, approval
```

---

### 7.2 승인 핸들러

**파일**: `handlers/approval_handler.py`

```python
pending_approvals: dict[str, ApprovalRequest] = {}  # in-memory, 재시작 시 초기화
```

**승인 버튼 클릭 처리**:
```python
@app.action("approve_action")
async def handle_approve(ack, body, client):
    await ack()  # Slack에 200 즉시 응답 (3초 이내 필수)

    value = json.loads(body["actions"][0]["value"])
    # value = {"request_id": "...", "action": "...", "params": {...}}

    req = pending_approvals.pop(request_id, None)
    if req is None: # 이미 처리됨 또는 만료
        ...
    if _is_expired(req):  # 120초 초과
        ...

    output = _execute_action(action, params)  # 실제 실행
```

**TTL 체크**:
```python
def _is_expired(req: ApprovalRequest) -> bool:
    elapsed = (datetime.now(timezone.utc) - req.created_at).total_seconds()
    return elapsed > cfg.APPROVAL_TIMEOUT_SEC  # 기본 120초
```

---

### 7.3 Alert 핸들러

**파일**: `handlers/alert_handler.py`

```python
@router.post("/webhook/alertmanager")
async def alertmanager_webhook(payload: dict, background_tasks: BackgroundTasks):
    # Alertmanager가 POST로 알람 전송
    for alert in payload.get("alerts", []):
        if alert.get("status") == "firing":
            background_tasks.add_task(_analyze_alert, alert)
```

**에이전트 분석 포맷**:
```
[CRITICAL] TargetDown (ns=kube-system)
Alert: TargetDown - kube-controller-manager is down.
Namespace: kube-system
Please diagnose and suggest resolution.
```

이 텍스트가 `run_agent()`로 전달되어 에이전트가 분석합니다.

---

## 8. 전체 요청 흐름

### 8.1 일반 조회 흐름

```
사용자: "@infra-agent flooding namespace pod 상태 알려줘"

1. Slack → bolt_app (Socket Mode 이벤트)
2. message_handler.handle_mention()
   - 멘션 제거 → "flooding namespace pod 상태 알려줘"
   - :thinking_face: 리액션 추가
3. run_agent("flooding namespace pod 상태 알려줘", channel_id="C1234")
   - loop.run_in_executor() → 스레드풀에서 agent.invoke() 실행
4. LangChain AgentExecutor
   - LLM: "get_pod_status를 호출해야겠다"
   - tool call: get_pod_status(namespace="flooding")
   - Kubernetes API → Pod 목록 반환
   - LLM: Final Answer 생성 (실제 Pod 이름/상태/재시작수 포함)
5. _enrich_output() → 모호한 표현 없음 → 그대로 반환
6. message_handler
   - _extract_approval() → 승인 요청 없음
   - chat_postMessage → 응답 전송
7. :thinking_face: 리액션 제거
```

### 8.2 파괴적 작업(승인 필요) 흐름

```
사용자: "@infra-agent flooding-server 레플리카 1개 추가해줘"

1. ~ 3. (위와 동일)
4. LangChain AgentExecutor
   - LLM: "현재 레플리카 수를 먼저 확인해야겠다"
   - tool call: get_pod_status(namespace="flooding")
     → 현재 3개 확인
   - LLM: "scale_deployment(name="flooding-server", replicas=4, namespace="flooding") 호출"
   - tool call → <APPROVAL_REQUEST> JSON 블록 반환
   - LLM: Final Answer에 블록 포함
5. _enrich_output() → 변경 없음
6. message_handler
   - _extract_approval() → APPROVAL_REQUEST 블록 파싱
   - format_agent_response() → 일반 응답 전송
   - create_approval_request() → UUID 생성, pending_approvals 저장
   - format_approval_request() → [✅ Approve] [❌ Reject] 버튼 전송
7. 사용자가 ✅ Approve 클릭
8. approval_handler.handle_approve()
   - ack() → Slack에 즉시 200 응답
   - pending_approvals에서 요청 조회
   - _is_expired() 확인 (120초 이내)
   - _execute_action("scale_deployment", {name, namespace, replicas})
   - execute_scale_deployment() → Kubernetes API patch
   - 결과 메시지로 버튼 메시지 업데이트
```

### 8.3 Alertmanager 알람 흐름

```
Alertmanager → POST http://infra-agent:8080/webhook/alertmanager
{
  "alerts": [{
    "status": "firing",
    "labels": {"alertname": "PodCrashLoopBackOff", "namespace": "flooding", ...},
    "annotations": {"description": "..."}
  }]
}

1. alert_handler.alertmanager_webhook()
   - "firing" 알람 필터링
   - background_tasks.add_task(_analyze_alert, alert)
2. _analyze_alert()
   - 알람 정보를 텍스트로 포맷
   - run_agent() 호출 (channel_id="alertmanager")
   - Slack 채널에 분석 결과 전송
```

---

## 9. 인프라 구성 (Kubernetes)

**파일**: `k8s/deployment.yaml`

### RBAC

```yaml
# ClusterRole - 에이전트가 가진 K8s 권한
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes", "events", "namespaces"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "deployments/scale"]
    verbs: ["get", "list", "watch", "patch", "update"]
```

> **중요**: ClusterRole을 사용하므로 클러스터 전체에 적용됩니다. 만약 특정 네임스페이스만 허용하려면 `Role`과 `RoleBinding`으로 범위를 제한하세요.

### 리소스 제한

```yaml
resources:
  requests:
    cpu: "200m"
    memory: "256Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

### 서비스

```yaml
type: NodePort
port: 8080
nodePort: 30200  # Alertmanager 웹훅용
```

Alertmanager의 `webhook_configs`에 `http://10.0.0.x:30200/webhook/alertmanager` 로 설정해야 합니다.

---

## 10. 환경 변수 및 시크릿

### 필수 환경변수 (Secret)

```bash
kubectl create secret generic infra-agent-secret \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_APP_TOKEN=xapp-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  -n flooding
```

### 선택적 환경변수 (ConfigMap 또는 Secret)

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `OPENAI_MODEL` | `gpt-4o` | 사용할 OpenAI 모델 |
| `PROMETHEUS_URL` | `http://prometheus-service.monitoring:9090` | Prometheus 주소 |
| `LOKI_URL` | `http://loki.monitoring:3100` | Loki 주소 |
| `SLACK_ALERT_CHANNEL` | `#infra-alerts` | 알람 전송 채널 |
| `APP_PORT` | `8080` | FastAPI 서버 포트 |
| `APPROVAL_TIMEOUT_SEC` | `120` | 승인 요청 만료 시간(초) |
| `KUBECONFIG_PATH` | (없음, in-cluster 자동 감지) | 로컬 테스트용 kubeconfig |

### Slack App 설정 요구사항

1. **Socket Mode** 활성화 필요 (App Token = `xapp-...`)
2. **Event Subscriptions**: `app_mention` 이벤트 구독
3. **Interactivity**: 버튼 클릭(Action) 처리를 위해 활성화
4. **OAuth Scopes**: `chat:write`, `reactions:write`, `reactions:read`
5. **Bot가 채널에 초대**되어 있어야 함 (`/invite @infra-agent`)

---

## 11. 배포 방법

### 로컬에서 배포

```bash
cd langchain-agent
bash scripts/deploy.sh
```

**deploy.sh 동작**:
1. `rsync`로 소스를 `gsmsv-1.yujun.kr`의 `/tmp/infra-agent/`로 전송
2. `nerdctl build`로 Docker 이미지 빌드 (Harbor에 push)
3. `nerdctl push`로 Harbor(`gsmsv-1.yujun.kr:28104/flooding/infra-agent:latest`)에 업로드
4. `kubectl rollout restart`로 Pod 재시작 후 완료 대기

### 최초 배포 (K8s 리소스 생성)

```bash
# Secret 먼저 생성
kubectl create secret generic infra-agent-secret \
  --from-literal=OPENAI_API_KEY=<key> \
  --from-literal=SLACK_BOT_TOKEN=<xoxb-...> \
  --from-literal=SLACK_APP_TOKEN=<xapp-...> \
  --from-literal=SLACK_SIGNING_SECRET=<secret> \
  -n flooding

# K8s 리소스 적용
kubectl apply -f k8s/deployment.yaml
```

### 로그 확인

```bash
ssh -p 27101 ubuntu@gsmsv-1.yujun.kr \
  'kubectl logs -n flooding -l app=infra-agent --tail=100 -f'
```

---

## 12. Runbook 구조 및 추가 방법

**파일**: `runbooks/runbook.yaml`

### 현재 등록된 런북

| ID | 패턴 | 설명 |
|----|------|------|
| `crashloop` | CrashLoopBackOff, crash | Pod 반복 재시작 |
| `oom_killed` | OOMKilled, out of memory | 메모리 초과 종료 |
| `high_error_rate` | high error, error rate, 5xx | HTTP 에러율 급증 |
| `node_disk_pressure` | DiskPressure, disk pressure | 노드 디스크 부족 |
| `pod_pending` | Pending, pending | Pod 스케줄링 실패 |
| `image_pull_error` | ImagePullBackOff, ErrImagePull | 이미지 풀 실패 |

### 런북 추가 방법

```yaml
# runbooks/runbook.yaml에 추가
runbooks:
  - id: new_runbook_id
    patterns:
      - "증상 키워드 1"
      - "증상 키워드 2"
    diagnosis:
      - "진단 단계 1: kubectl 명령어 예시"
      - "진단 단계 2: Prometheus 쿼리 예시"
    actions:
      - type: approval_required    # 승인 필요
        tool: scale_deployment
        description: "스케일 조정"
      - type: auto                 # 자동 실행 가능
        tool: get_pod_status
        description: "Pod 상태 확인"
```

추가 후 이미지 재빌드 없이 ConfigMap으로 마운트하거나, `deploy.sh`로 재배포합니다.

---

## 13. 알려진 제약사항 및 설계 결정 배경

### 13.1 메모리 영속성 없음

```
현상: 에이전트 재시작 시 모든 대화 컨텍스트 소실
이유: in-memory dict 사용 (Redis 등 미도입)
해결: 필요 시 ConversationBufferWindowMemory를 Redis 기반으로 교체 가능
     langchain_community.chat_message_histories.RedisChatMessageHistory 사용
```

### 13.2 승인 요청 재시작 시 소실

```
현상: 에이전트 재시작 시 pending_approvals dict가 초기화되어 버튼이 무효화
이유: 동일한 in-memory 저장 이슈
해결: 재시작이 잦지 않으므로 현재는 허용. 중요하다면 Redis/DB 사용
```

### 13.3 단일 인스턴스

```
현상: HPA를 사용한 수평 확장 불가 (승인 요청 in-memory 공유 불가)
이유: pending_approvals가 프로세스 메모리에 존재
해결: 확장이 필요하다면 공유 저장소(Redis) 도입 필수
```

### 13.4 PromQL 중괄호 이스케이프

```
현상: SYSTEM_PROMPT에 {namespace="..."} 패턴이 있으면 ChatPromptTemplate이
     템플릿 변수로 오인
해결: {{namespace="..."}} 이중 이스케이프 OR SystemMessage(content=...) 사용
현재: SystemMessage 객체 방식으로 해결 (파싱 자체 스킵)
```

### 13.5 OpenAI Tools 에이전트로 전환 이유

```
이전: create_react_agent (hwchase17/react 프롬프트 기반 텍스트 파싱)
문제: "Missing 'Action:' after 'Thought:'" 파싱 에러 → iteration 소모 → 한도 초과
현재: create_openai_tools_agent (native function calling)
장점: 파싱 에러 없음, 툴 파라미터 타입 안전성
```

### 13.6 scale_deployment가 Exception 대신 문자열 반환

```
이전: raise RequiresApprovalError(...)
문제: LangChain이 내부에서 예외를 잡아 error observation으로 변환
     LLM이 "승인 필요"라는 텍스트만 출력, Slack 버튼 미생성
현재: <APPROVAL_REQUEST> JSON 블록을 문자열로 반환
     message_handler가 Final Answer + intermediate_steps 두 경로로 탐지
```

---

## 14. 트러블슈팅 가이드

### "Input to ChatPromptTemplate is missing variables" 에러

```
원인: SYSTEM_PROMPT 또는 툴 설명에 {변수명} 형태의 단일 중괄호가 있음
해결: orchestrator.py에서 ("system", SYSTEM_PROMPT) 대신
     SystemMessage(content=SYSTEM_PROMPT) 사용 확인
```

### 승인 버튼이 나타나지 않음

```
원인 1: 툴이 <APPROVAL_REQUEST> 블록을 반환했으나 LLM이 Final Answer에 포함하지 않음
해결: message_handler.py에서 intermediate_steps도 탐색하는 코드 확인
     (if not approval: for _action, observation in result.get("intermediate_steps", []):)

원인 2: _extract_approval() 정규식이 블록 형식과 불일치
해결: 툴이 반환하는 형식이 <APPROVAL_REQUEST>\n{...}\n</APPROVAL_REQUEST> 인지 확인
```

### "Agent stopped due to iteration limit" 반복 발생

```
원인: 툴 에러가 반복되거나 LLM이 루프에 빠짐
해결:
  1. verbose=True 로그에서 어떤 툴이 계속 에러를 내는지 확인
  2. max_iterations 증가 고려 (현재 15)
  3. 툴 에러 메시지를 더 명확하게 수정
```

### Prometheus/Loki 데이터 없음

```
원인: 서비스 URL이 잘못되었거나 네트워크 접근 불가
확인:
  kubectl exec -n flooding <pod> -- curl http://prometheus-service.monitoring:9090/api/v1/query?query=up
  kubectl exec -n flooding <pod> -- curl http://loki.monitoring:3100/loki/api/v1/labels
```

### scale_deployment 후 실제로 변경이 안 됨

```
원인: RBAC 권한 부족
확인:
  kubectl auth can-i patch deployments/scale -n flooding --as=system:serviceaccount:flooding:infra-agent-sa
해결: k8s/deployment.yaml의 ClusterRole에 필요한 권한 추가 후 재적용
```

### Alertmanager 웹훅이 도달하지 않음

```
확인:
  1. NodePort 30200이 열려 있는지 확인
  2. Alertmanager values.yaml의 webhook URL 확인
     url: http://10.0.0.x:30200/webhook/alertmanager
  3. kubectl logs로 POST /webhook/alertmanager 요청이 오는지 확인
```
