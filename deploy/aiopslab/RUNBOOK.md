# AIOpsLab Benchmark Runbook (OpsPilot)

本文档是当前分支（`feat/aiopslab-benchmark-adapter`）跑 AIOpsLab benchmark 的
权威操作手册：记录一键恢复脚本、全部 YAML 配置、日常运行命令和常见排障。
它取代 main 分支上旧的 `deploy/aiopslab/README.md`（poetry/Linux VM/DeathStarBench
方案）。

## 1. 架构：三个平面

```
注入面（实验者）      AIOpsLab bridge + Chaos Mesh     全权限 admin kubeconfig
观测面（被测者）      OpsPilot runtime + MCP 工具       窄权限 observer SA（只读）
数据面（受害者）      otel-demo (astronomy-shop)        被观测 + 被注入
```

- 故障是**真实**的 Chaos Mesh 注入（pod-failure / network loss），不是 flagd
  开关；agent 只能从症状（重启、延迟、错误率）推断。
- agent 的 kubectl 是 namespaced 只读角色，**读不到 configmaps**（flagd 不可见）、
  没有 secrets/exec/写权限。
- 每次 run 可以切换**常驻模式**（复用已部署环境，~1 分钟）或**一次性模式**
  （完整部署+清理，~13 分钟）。

## 2. 本目录文件

| 文件 | 作用 |
| --- | --- |
| `setup-benchmark.ps1` | 一键恢复脚本（幂等，可反复执行） |
| `ops-pilot-config.example.yaml` | benchmark 调优后的 ops_pilot 配置模板 |
| `RUNBOOK.md` | 本文档 |

配套文件（在仓库其他位置）：

- `benchmarks/aiopslab_bridge/app.py` — bridge（AIOpsLab 生命周期 + 自定义问题注册 + 常驻模式）
- `benchmarks/aiopslab_bridge/problems/astronomy_shop_faults.py` — 自定义 Chaos 故障问题
- `benchmarks/aiopslab_bridge/rbac/observer.yaml` — 观测者只读 RBAC
- `benchmarks/aiopslab_bridge/rbac/create-observer-kubeconfig.ps1` — 生成观测者 kubeconfig

## 3. 前置条件

本机（Windows，PowerShell）：

- `kubectl` + `gardenlogin`，context 指向 Gardener shoot（试用集群可清空）
- `winget`（用于装 helm）、`git`、`uv`、`node`/`npx`
- Python 3.12（用 `uv python install 3.12`，AIOpsLab 要求 `>=3.11,<3.13`）

集群（Gardener shoot）：

- 约 4 vCPU / 13 GiB（2 × 2 vCPU / 6.8 GiB 可用）
- 允许 privileged 容器（Chaos Mesh daemonset 需要；已验证可行）
- 存储类默认 EBS；AIOpsLab 会临时装 OpenEBS 并把 `openebs-hostpath` 设为默认

模型（`config/config.yaml` + `.env`）：三个通道任选其一，否则跑不动：

- opencode.ai free（`deepseek-v4-flash-free`）——实测会被 429 限流
- opencode.ai 付费模型（同 key，需账户绑定支付方式，如 `claude-sonnet-4-6`）
- SAP AI Core（`.env` 填真实 `AICORE_*`，`provider: sap`）

## 4. 一键恢复

```powershell
powershell -ExecutionPolicy Bypass -File deploy/aiopslab/setup-benchmark.ps1
```

脚本幂等，做了这些事：

1. 刷新 PATH；缺 helm 时用 winget 安装；校验 kubectl/git/uv/npx；
2. `uv python install 3.12`；
3. 缺省时 clone `microsoft/AIOpsLab` 到 `D:\dev\projects\AIOpsLab`（浅克隆，
   astronomy-shop 是远程 chart，不需要 submodules），建 venv、装依赖和 uvicorn；
4. 写 `aiopslab/config.yml`（`k8s_host: localhost`）；
5. 创建注入面 admin：`kube-system/aiopslab-admin` SA + cluster-admin
   ClusterRoleBinding + 静态 token kubeconfig
   （`D:\dev\projects\AIOpsLab\aiopslab-admin.kubeconfig`）。这是必须的：
   **kubernetes Python client 无法解析 gardenlogin exec 凭证**；
6. 创建 `astronomy-shop` namespace + 观测者 RBAC + 生成
   `C:\Users\<you>\.kube\ops-pilot-observer.kubeconfig`；
7. 缺省时从 `ops-pilot-config.example.yaml` 生成 `config/config.yaml`，并提示
   检查 `.env`。

脚本最后打印两条启动命令（见 §7）。

## 5. 配置文件（YAML）

### 5.1 `aiopslab/config.yml`（AIOpsLab 侧，脚本自动生成）

```yaml
# Kubernetes control node
k8s_host: localhost   # localhost = 控制器本机持有 shoot kubeconfig（我们的场景）
k8s_user: your_username
ssh_key_path: ~/.ssh/id_rsa
data_dir: data
qualitative_eval: false
print_session: false
```

`k8s_host: localhost` 是关键：AIOpsLab 所有 kubectl/helm 命令在本机执行，命中当前
kubeconfig context（shoot）。`k8s_user`/`ssh_key_path` 只有在填远程主机名走 SSH
时才用得到，托管集群用不到。

### 5.2 ops_pilot `config/config.yaml`

完整模板见 [`ops-pilot-config.example.yaml`](./ops-pilot-config.example.yaml)。
对 benchmark 最关键的几段：

```yaml
model:
  provider: openai
  model_name: deepseek-v4-flash-free   # 或付费模型 / sap provider
  base_url: https://opencode.ai/zen/v1 # API ROOT，客户端自己补 /chat/completions

persistence:
  backend: memory   # postgres 在 Windows ProactorEventLoop 上跑不了

mcpServers:
  kubernetes:
    required: true
    transport: stdio
    command: npx
    args:
      - -y
      - kubernetes-mcp-server@latest
      - --disable-multi-cluster
      - --kubeconfig
      - C:/Users/<you>/.kube/ops-pilot-observer.kubeconfig   # 窄权限观测者
    env:
      KUBECONFIG: C:/Users/<you>/.kube/ops-pilot-observer.kubeconfig
  # jaeger / prometheus / opensearch：旧 otel-demo 端点，已设 required: false，
  # 等 AIOpsLab 自己的 Jaeger/Prometheus 暴露出来再启用
```

### 5.3 观测者 RBAC（`benchmarks/aiopslab_bridge/rbac/observer.yaml`）

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ops-pilot
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ops-pilot-observer
  namespace: ops-pilot
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ops-pilot-observer
  namespace: astronomy-shop
rules:
  - apiGroups: [""]
    resources: [pods, pods/log, events, endpoints, services, persistentvolumeclaims, replicationcontrollers]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: [deployments, statefulsets, replicasets, daemonsets]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: [ingresses, networkpolicies]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["autoscaling"]
    resources: [horizontalpodautoscalers]
    verbs: ["get", "list", "watch"]
  # 注意：没有 configmaps（flagd 不可见）、没有 secrets、没有 exec、没有写操作
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ops-pilot-observer
  namespace: astronomy-shop
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: ops-pilot-observer
subjects:
  - kind: ServiceAccount
    name: ops-pilot-observer
    namespace: ops-pilot
```

SA 放在稳定的 `ops-pilot` namespace（token 跨 run 有效）；Role/RoleBinding 在
`astronomy-shop`（每次 run 会重建 namespace，bridge 在 init 后自动重放）。

### 5.4 `.env`（键名，值不落库）

```
OPS_PILOT_CONFIG, MODEL_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
DATABASE_URL, OPEN_SANDBOX_API_KEY, OTEL_BASIC_AUTH_USER, OTEL_BASIC_AUTH_PASSWORD,
MCP_BASIC_AUTH_HEADER, OTEL_SHOOT_DOMAIN,
AICORE_CLIENT_ID, AICORE_CLIENT_SECRET, AICORE_AUTH_URL, AICORE_BASE_URL,
AICORE_RESOURCE_GROUP   # 用 SAP provider 时填真实值；当前是空占位符
```

## 6. 自定义问题

已注册（bridge 启动时自动注入 registry）：

| problem id | 故障 |
| --- | --- |
| `astronomy_shop_payment_pod_kill-localization-1` | Chaos Mesh pod-failure（payment，1800s） |
| `astronomy_shop_payment_network_loss-localization-1` | Chaos Mesh 99% 网络丢包（payment，1800s） |

注入器做了三个适配：selector 用 OTel demo 的 `app.kubernetes.io/name` 标签（不是
AIOpsLab 内置的 `io.kompose.service`）；临时 YAML 写到平台 temp 目录（原版写死
`/tmp`，Windows 会挂）；`kubectl apply --validate=false` 跳过 OpenAPI 下载超时。

## 7. 日常运行

Terminal A（bridge）：

```powershell
cd D:\dev\projects\AIOpsLab
$env:KUBECONFIG = "D:\dev\projects\AIOpsLab\aiopslab-admin.kubeconfig"
.venv\Scripts\python.exe D:\dev\projects\ops-agent-platform\benchmarks\aiopslab_bridge\app.py
```

健康检查：`Invoke-RestMethod http://127.0.0.1:1819/health`

Terminal B（agent）：

```powershell
cd D:\dev\projects\ops-agent-platform\services\agent
uv run ops_pilot benchmark --base-url http://127.0.0.1:1819 `
  --problem astronomy_shop_payment_pod_kill-localization-1 --persistent
```

常驻/一次性：

- `--persistent`（默认）：复用已部署环境，首跑 ~5 分钟部署，之后每次 ~1 分钟；
- `--no-persistent`：完整生命周期（每次删 namespace 重装 + 跑完清理，~13 分钟）；
- 直接调 bridge 时在 body 传 `"persistent": true/false` 可覆盖；
- 环境变量 `AIOPSLAB_PERSISTENT=0` 可全局关掉常驻。

## 8. 验证

```powershell
# 观测者边界（应全部符合预期）
kubectl auth can-i get pods -n astronomy-shop --as=system:serviceaccount:ops-pilot:ops-pilot-observer
kubectl auth can-i get configmaps -n astronomy-shop --as=system:serviceaccount:ops-pilot:ops-pilot-observer   # no
kubectl auth can-i delete pods -n astronomy-shop --as=system:serviceaccount:ops-pilot:ops-pilot-observer      # no

# 运行时（确认 MCP 加载）
cd services/agent
uv run ops_pilot settings
uv run ops_pilot status   # kubernetes MCP 工具应出现，jaeger/prometheus 可选
```

## 9. 清理 / 重置

```powershell
# 停 bridge 后，清理 benchmark 部署（常驻模式留下的热环境）
kubectl delete ns astronomy-shop observe openebs ops-pilot
kubectl delete sc openebs-hostpath openebs-device --ignore-not-found
kubectl delete clusterrolebinding aiopslab-admin --ignore-not-found
kubectl delete sa aiopslab-admin -n kube-system --ignore-not-found
# Chaos Mesh（含 CRD）如需彻底移除：
helm uninstall chaos-mesh -n chaos-mesh
kubectl delete ns chaos-mesh
kubectl get crd -o name | Select-String 'chaos-mesh|openebs' | ForEach-Object { kubectl delete $_.ToString().Trim() }
```

注意：删 SA 前先删 ClusterRoleBinding（否则 SA 会失去权限删不掉自己，需用
gardenlogin 默认凭证补删）。本地两个 kubeconfig 的 token 随 SA 删除失效，下次
重跑 `setup-benchmark.ps1` 会重新生成。

## 10. 排障

| 现象 | 原因 / 处理 |
| --- | --- |
| bridge 报 `'helm' is not recognized` | 启动 bridge 的 shell 没刷新 PATH：先执行 `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')` 再启动 |
| Python client 报 gardenlogin `ExecCredential does not contain cluster information` | kubernetes Python client 不支持 gardenlogin exec 插件；bridge 进程必须设 `KUBECONFIG=aiopslab-admin.kubeconfig`（静态 token）。import 时的那条 gardenlogin 报错只是 observer 模块噪音，可忽略 |
| `kubectl apply` 报 OpenAPI 校验超时导致故障没注入 | 已内置 `--validate=false`；确认用的是最新 bridge 代码 |
| `ops_pilot status` 报 Psycopg ProactorEventLoop | persistence 必须是 `memory`（Windows） |
| 模型 429 `FreeUsageLimitError` | opencode free 额度用尽：等重置 / 绑支付方式换付费模型 / 填 AICORE 用 SAP |
| 模型 401 `CreditsError` | opencode 账户没有支付方式，付费模型不可用 |
| 常驻模式下 agent 找不到故障 | 检查 `kubectl get podchaos -n astronomy-shop`；确认注入日志出现 `Applied pod-kill chaos experiment` 且无 error |
| 集群太小装不下 | 首跑前清掉其他占用；2 节点 ~13 GiB 刚好够一套 demo + Prometheus + Chaos Mesh |

## 11. 已知限制

- kernel/BPF 层故障（`err_inject`）需要节点 SSH + root，托管 Gardener shoot 不可用；
- 观测面目前只有 kubectl（只读）；AIOpsLab 自己的 Prometheus（`observe`）和
  Jaeger（astronomy-shop chart 自带）还没通过 ingress/MCP 暴露，metrics/traces
  工具待补；
- 单次只能跑一个 run（bridge 对并发返回 409）；
- 常驻模式会让整套 demo 一直占用集群资源（约 4 vCPU / 13 GiB）。
