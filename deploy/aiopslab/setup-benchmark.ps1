# One-click restore of the AIOpsLab benchmark environment (idempotent).
#
# What it does:
#   1. Ensures helm / kubectl / git / uv / node are available (installs helm
#      via winget when missing).
#   2. Ensures Python 3.12 (uv) and the AIOpsLab checkout + venv + deps.
#   3. Writes aiopslab/config.yml with k8s_host: localhost.
#   4. Creates the injection-plane admin ServiceAccount + static kubeconfig
#      (the Kubernetes Python client cannot use the gardenlogin exec plugin).
#   5. Creates the astronomy-shop namespace + read-only observer RBAC and
#      generates the observer kubeconfig for the agent's Kubernetes MCP.
#   6. Bootstraps config/config.yaml from deploy/aiopslab/ops-pilot-config.example.yaml
#      when missing, and prints the two launch commands.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File deploy/aiopslab/setup-benchmark.ps1

param(
    [string]$AIOpsLabDir = "D:\dev\projects\AIOpsLab",
    [string]$AdminKubeconfig = "",
    [string]$ObserverKubeconfig = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $AdminKubeconfig) { $AdminKubeconfig = Join-Path $AIOpsLabDir "aiopslab-admin.kubeconfig" }
if (-not $ObserverKubeconfig) { $ObserverKubeconfig = Join-Path $HOME ".kube\ops-pilot-observer.kubeconfig" }

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Assert-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name not found on PATH. $Hint"
    }
}

function Invoke-Kubectl {
    param([string[]]$Arguments)
    & kubectl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function New-AdminToken {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $token = & kubectl @("create", "token", "aiopslab-admin", "-n", "kube-system", "--duration=24h")
        if ($LASTEXITCODE -eq 0 -and $token) {
            return ($token | Select-Object -Last 1).Trim()
        }
        Write-Warning "kubectl create token failed (attempt $attempt/3); retrying..."
        Start-Sleep -Seconds 5
    }
    throw "kubectl create token failed after 3 attempts"
}

Write-Host "==> 1. Toolchain (helm / kubectl / git / uv / node)"
Refresh-Path
if (-not (Get-Command helm -ErrorAction SilentlyContinue)) {
    Write-Host "Installing helm via winget..."
    winget install Helm.Helm --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
}
Assert-Command helm "Install it with: winget install Helm.Helm"
Assert-Command kubectl "Point kubectl at the shoot (kubectl config use-context ...)."
Assert-Command git "Install Git for Windows."
Assert-Command uv "Install uv (https://docs.astral.sh/uv/)."
Assert-Command npx "Install Node.js (required by the kubernetes MCP server)."

Write-Host "Current kubectl context: $(kubectl config current-context)"

Write-Host "==> 2. Python 3.12 (uv)"
uv python install 3.12 | Out-Null

Write-Host "==> 3. AIOpsLab checkout + venv"
if (-not (Test-Path (Join-Path $AIOpsLabDir ".git"))) {
    git clone --depth 1 https://github.com/microsoft/AIOpsLab $AIOpsLabDir
}
Push-Location $AIOpsLabDir
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        uv venv --python 3.12
    }
    uv pip install -e . | Out-Null
    uv pip install uvicorn | Out-Null
} finally {
    Pop-Location
}

Write-Host "==> 4. aiopslab/config.yml (k8s_host: localhost)"
$cfgPath = Join-Path $AIOpsLabDir "aiopslab\config.yml"
if (-not (Test-Path $cfgPath)) {
    Copy-Item (Join-Path $AIOpsLabDir "aiopslab\config.yml.example") $cfgPath
}
$cfg = Get-Content $cfgPath -Raw
$cfg = $cfg -replace "k8s_host: control_node_hostname.*", "k8s_host: localhost"
Set-Content -Path $cfgPath -Value $cfg -Encoding utf8

Write-Host "==> 5. Injection-plane admin kubeconfig"
kubectl create serviceaccount aiopslab-admin -n kube-system --dry-run=client -o yaml | kubectl apply -f - | Out-Null
kubectl create clusterrolebinding aiopslab-admin --clusterrole=cluster-admin --serviceaccount=kube-system:aiopslab-admin --dry-run=client -o yaml | kubectl apply -f - | Out-Null
$token = New-AdminToken
$server = (Invoke-Kubectl @("config", "view", "--raw", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")).Trim()
$caData = (Invoke-Kubectl @("config", "view", "--raw", "--minify", "-o", "jsonpath={.clusters[0].cluster.certificate-authority-data}")).Trim()
if (-not $caData) {
    $caFile = (Invoke-Kubectl @("config", "view", "--raw", "--minify", "-o", "jsonpath={.clusters[0].cluster.certificate-authority}")).Trim()
    if ($caFile) { $caData = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $caFile))) }
}
$cluster = @{ server = $server }
if ($caData) { $cluster["certificate-authority-data"] = $caData } else { $cluster["insecure-skip-tls-verify"] = $true }
$kubeconfig = [ordered]@{
    apiVersion = "v1"
    kind = "Config"
    clusters = @(@{ name = "aiopslab-admin"; cluster = $cluster })
    contexts = @(@{ name = "aiopslab-admin"; context = @{ cluster = "aiopslab-admin"; user = "aiopslab-admin" } })
    "current-context" = "aiopslab-admin"
    users = @(@{ name = "aiopslab-admin"; user = @{ token = $token } })
}
$kubeconfig | ConvertTo-Json -Depth 6 | Set-Content -Path $AdminKubeconfig -Encoding utf8
Write-Host "Admin kubeconfig: $AdminKubeconfig"

Write-Host "==> 6. Observer RBAC + kubeconfig (agent's read-only identity)"
kubectl create namespace astronomy-shop --dry-run=client -o yaml | kubectl apply -f - | Out-Null
$observerScript = Join-Path $RepoRoot "benchmarks\aiopslab_bridge\rbac\create-observer-kubeconfig.ps1"
if (-not (Test-Path $observerScript)) {
    throw "Observer kubeconfig script not found: $observerScript"
}
powershell -NoProfile -ExecutionPolicy Bypass -File $observerScript -OutFile $ObserverKubeconfig
Write-Host "Observer kubeconfig: $ObserverKubeconfig"

Write-Host "==> 7. ops_pilot config/config.yaml"
$opsConfig = Join-Path $RepoRoot "config\config.yaml"
if (-not (Test-Path $opsConfig)) {
    Copy-Item (Join-Path $PSScriptRoot "ops-pilot-config.example.yaml") $opsConfig
    Write-Host "Wrote $opsConfig from the example. Edit the model section and the"
    Write-Host "observer kubeconfig path (C:/Users/<you>/.kube/ops-pilot-observer.kubeconfig)."
} else {
    Write-Host "$opsConfig already exists (kept). Verify its kubernetes MCP"
    Write-Host "kubeconfig points at $ObserverKubeconfig."
}
if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    Write-Warning ".env missing - copy .env.example and add MODEL_API_KEY (or AICORE_* credentials)."
}

Write-Host ""
Write-Host "==> Done. Launch the benchmark:"
Write-Host ""
Write-Host "Terminal A (bridge, injection plane):"
Write-Host "  cd $AIOpsLabDir"
Write-Host "  `$env:KUBECONFIG = '$AdminKubeconfig'"
Write-Host "  .venv\Scripts\python.exe $RepoRoot\benchmarks\aiopslab_bridge\app.py"
Write-Host ""
Write-Host "Terminal B (OpsPilot agent):"
Write-Host "  cd $RepoRoot\services\agent"
Write-Host "  uv run ops_pilot benchmark --base-url http://127.0.0.1:1819 --problem astronomy_shop_payment_pod_kill-localization-1 --persistent"
