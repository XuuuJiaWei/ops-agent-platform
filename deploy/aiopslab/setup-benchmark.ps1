# Bootstrap a local AIOpsLab checkout for OpsPilot benchmark runs.
#
# This script follows AIOpsLab's official editable-install workflow, but keeps
# the checkout outside the OpsPilot virtual environment. `pnpm benchmark`
# layers it into a one-command uv environment with --with-editable.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File deploy/aiopslab/setup-benchmark.ps1

param(
    [string]$AIOpsLabDir = "D:\dev\projects\AIOpsLab",
    [ValidateSet("localhost", "kind")]
    [string]$KubernetesHost = "localhost"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$AgentDir = Join-Path $RepoRoot "services\agent"

function Assert-Command {
    param([string]$Name, [string]$Hint)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name not found on PATH. $Hint"
    }
}

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Assert-Command git "Install Git for Windows."
Assert-Command helm "Install it with: winget install Helm.Helm"
Assert-Command kubectl "Install kubectl and select the target cluster context."
Assert-Command uv "Install uv from https://docs.astral.sh/uv/."

Write-Host "Current kubectl context:"
Invoke-Checked kubectl @("config", "current-context")

if (-not (Test-Path (Join-Path $AIOpsLabDir ".git"))) {
    Write-Host "Cloning AIOpsLab with submodules into $AIOpsLabDir ..."
    Invoke-Checked git @("clone", "--recurse-submodules", "https://github.com/microsoft/AIOpsLab", $AIOpsLabDir)
}

$AIOpsLabConfig = Join-Path $AIOpsLabDir "aiopslab\config.yml"
if (-not (Test-Path $AIOpsLabConfig)) {
    Copy-Item (Join-Path $AIOpsLabDir "aiopslab\config.yml.example") $AIOpsLabConfig
}
$config = Get-Content $AIOpsLabConfig -Raw
if ($config -match "(?m)^k8s_host:\s*") {
    $config = $config -replace "(?m)^k8s_host:\s*.*$", "k8s_host: $KubernetesHost"
} else {
    $config += "`nk8s_host: $KubernetesHost`n"
}
Set-Content -Path $AIOpsLabConfig -Value $config -Encoding utf8

Push-Location $AgentDir
try {
    Invoke-Checked uv @("sync")
    # This validates the exact ephemeral dependency mechanism used by
    # `pnpm benchmark`; it does not install AIOpsLab into .venv.
    Invoke-Checked uv @("run", "--with-editable", $AIOpsLabDir, "python", "-c", "import aiopslab; print(aiopslab.__file__)")
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "AIOpsLab is ready. Add the following to $RepoRoot\.env:"
Write-Host "  OPS_PILOT_AIOPSLAB_DIR=$AIOpsLabDir"
Write-Host "  OPS_PILOT_BENCHMARK_MODEL_PROVIDER=<sap|openai|deepseek|anthropic|...>"
Write-Host "  OPS_PILOT_BENCHMARK_MODEL_NAME=<tool-calling-model>"
Write-Host "  MODEL_API_KEY=<required for non-SAP providers>"
Write-Host "  OPS_PILOT_BENCHMARK_KUBECONFIG=<optional kubeconfig for Kubernetes MCP>"
Write-Host ""
Write-Host "Run: pnpm benchmark -- --problem <problem-id> --max-steps 30"
