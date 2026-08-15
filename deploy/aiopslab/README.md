# AIOpsLab (Eval Controller)

This directory records how to deploy **Microsoft AIOpsLab** as the evaluation
controller for `ops-agent-platform`, targeting a Kubernetes cluster (the
Gardener shoot, or local `kind`).

> Unlike the other `deploy/` stacks (docker-compose), AIOpsLab is a **Python
> framework that runs on a controller machine** and deploys benchmark
> applications *into* a cluster via Helm/kubectl. There is no container to run
> here — this README bootstraps the controller and points it at a cluster.
>
> Planning context: [`docs/design/aiopslab-switch-spec.md`](../../docs/design/aiopslab-switch-spec.md)
> (switch plan, resource matrix, risks). Comparison: [`docs/reference/aiopslab-comparison.md`](../../docs/reference/aiopslab-comparison.md).

## Architecture

```
Linux VM / WSL2 (controller)          ┌─ Gardener shoot / kind (target cluster) ─┐
  AIOpsLab framework (poetry, py3.11) │  benchmark app namespace (hotel/social/…)│
  ├─ Orchestrator + Session           │  Chaos Mesh (symptom faults)             │
  ├─ clients/ops_pilot.py  ← agent    │  Prometheus / Jaeger (telemetry)         │
  └─ fault injectors + evaluators     └──────────────────────────────────────────┘
```

- **Controller** needs: Linux (VM or WSL2), Python 3.11, Poetry, `kubectl`,
  `helm`, `git`, SSH key (only for OS-level faults), Docker (only for a few
  virtualization faults). A 2 vCPU / 4 GiB VM is enough.
- **Cluster** sizing: see the resource matrix in the switch spec (§3.6 / §8).
  The current shoot (`garden-cloud--stzoojqj5i`, ~13 GiB) is **not enough** for
  the full suite; use a dedicated worker pool or a separate shoot (≥16–24 GiB).

## Install (controller)

```bash
# 1. Clone with submodules (aiopslab-applications contains app charts/manifests)
git clone --recurse-submodules https://github.com/microsoft/AIOpsLab.git
cd AIOpsLab

# 2. Python 3.11 + Poetry
poetry env use python3.11
poetry install
eval $(poetry env activate)

# 3. Config
cp aiopslab/config.yml.example aiopslab/config.yml
# edit aiopslab/config.yml  (see config.yml.example below)
```

A ready-to-run bootstrap script is included: `./controller-setup.sh`.

## Config (`aiopslab/config.yml`)

See [`config.yml.example`](./config.yml.example). Key fields:

| Field | Meaning |
| --- | --- |
| `k8s_host` | `kind` for a local kind cluster; `localhost` when the controller itself has the shoot kubeconfig; otherwise the control-plane hostname |
| `k8s_user` | user on the control-plane/controller (ignored for kind) |
| `ssh_key_path` | SSH key path (needed only for OS-level faults on workers) |
| `data_dir` | where results/plots/telemetry are stored (`data`) |
| `qualitative_eval` | `true` enables LLM-as-judge (extra LLM calls) |
| `print_session` | print the session trace after completion |

## Point at the Gardener shoot

The controller uses the **current `kubectl` context**, so just make the shoot
context active on the controller:

```bash
kubectl config use-context garden-cloud--stzoojqj5i-external
kubectl get nodes          # verify
```

Notes for the shoot:
- **Storage**: do NOT install OpenEBS — that is only for local kind. Gardener
  provides its own StorageClasses for the mongo/redis PVCs used by the apps.
- **Chaos Mesh** (only for symptom-level faults) must be installed once:

  ```bash
  helm repo add chaos-mesh https://charts.chaos-mesh.org
  helm repo update
  helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
    --namespace chaos-mesh --create-namespace --set dashboard.create=true
  ```

  Verify `chaos-daemon` can reach the node container runtime
  (`/run/containerd/containerd.sock` on Garden Linux). Not yet validated on
  this shoot — see spec §5.
- **OS-level faults** need SSH + root on the worker nodes; the shoot has no
  worker SSH configured, so `OSFaultInjector` (e.g. `disk_woreout`) is not
  usable until the shoot spec is updated.

## Smoke test (no LLM, no cluster changes beyond the app)

The official integration smoke test runs the lightest problem
(`noop_detection_hotel_reservation-1`) with a dummy agent that just submits:

```bash
cd AIOpsLab
poetry run pytest tests/integration/smoke_test.py -v -s
```

Interactive human-as-agent check:

```bash
python cli.py
(aiopslab) $ start noop_detection_hotel_reservation-1
```

## Running our ops_pilot as the agent

AIOpsLab expects an agent with `init_context(...)` + `async get_action(...)`.
The switch spec (§4.2) plans `clients/ops_pilot.py` that maps AIOpsLab actions
(telemetry APIs, `exec_shell`, `submit`) onto the ops_pilot runtime. Until that
client exists, use the built-in clients (e.g. `python clients/gpt.py`) to
validate the environment.

## Useful Commands

```bash
cd AIOpsLab
eval $(poetry env activate)

# List problems / run a specific one with a built-in client
python clients/client.py --agent gpt --problem-id pod_failure_hotel_res-detection-1 --max-steps 10

# Remote REST service (optional), then curl /health /problems /agents /simulate
SERVICE_HOST=0.0.0.0 SERVICE_PORT=1818 python service.py

# Cluster-side inspection
kubectl get ns | grep -E 'hotel|social|astronomy|chaos|prometheus'
kubectl get pods -n test-hotel-reservation
```

## Teardown

Apps are cleaned up by the orchestrator after each problem
(`app.cleanup()`), which uninstalls the app Helm release. To fully reset:

```bash
# per-app namespace
kubectl delete ns test-hotel-reservation
# chaos mesh (if installed)
helm uninstall chaos-mesh -n chaos-mesh && kubectl delete ns chaos-mesh
```
