# Generate a kubeconfig for OpsPilot's Kubernetes MCP server that authenticates
# as the read-only observer ServiceAccount (token valid for 24h by default).
#
# Usage:
#   powershell -File benchmarks/aiopslab_bridge/rbac/create-observer-kubeconfig.ps1
param(
    [string]$OutFile = "ops-pilot-observer.kubeconfig",
    [string]$TokenDuration = "24h"
)

$ErrorActionPreference = "Stop"

function Invoke-Kubectl {
    param([string[]]$Arguments)
    & kubectl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function New-ObserverToken {
    # TokenRequest can hit transient API server timeouts; retry a few times.
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $token = & kubectl @("create", "token", "ops-pilot-observer", "-n", "ops-pilot", "--duration=$TokenDuration")
        if ($LASTEXITCODE -eq 0 -and $token) {
            return ($token | Select-Object -Last 1).Trim()
        }
        Write-Warning "kubectl create token failed (attempt $attempt/3); retrying..."
        Start-Sleep -Seconds 5
    }
    throw "kubectl create token failed after 3 attempts"
}

Invoke-Kubectl @("apply", "-f", (Join-Path $PSScriptRoot "observer.yaml")) | Out-Null

$token = New-ObserverToken
$server = (Invoke-Kubectl @("config", "view", "--raw", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")).Trim()
$caData = (Invoke-Kubectl @("config", "view", "--raw", "--minify", "-o", "jsonpath={.clusters[0].cluster.certificate-authority-data}")).Trim()
if (-not $caData) {
    $caFile = (Invoke-Kubectl @("config", "view", "--raw", "--minify", "-o", "jsonpath={.clusters[0].cluster.certificate-authority}")).Trim()
    if ($caFile) {
        $caData = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $caFile)))
    }
}

$cluster = @{ server = $server }
if ($caData) {
    $cluster["certificate-authority-data"] = $caData
} else {
    $cluster["insecure-skip-tls-verify"] = $true
}

$kubeconfig = [ordered]@{
    apiVersion = "v1"
    kind = "Config"
    clusters = @(@{ name = "ops-pilot-observer"; cluster = $cluster })
    contexts = @(@{ name = "ops-pilot-observer"; context = @{ cluster = "ops-pilot-observer"; user = "ops-pilot-observer" } })
    "current-context" = "ops-pilot-observer"
    users = @(@{ name = "ops-pilot-observer"; user = @{ token = $token } })
}

$kubeconfig | ConvertTo-Json -Depth 6 | Set-Content -Path $OutFile -Encoding utf8
Write-Host "Wrote $OutFile (token valid $TokenDuration). Point the Kubernetes MCP server at this file."
