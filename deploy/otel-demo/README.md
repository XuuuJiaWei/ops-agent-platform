# Rebuild the OTel Demo Shoot

This directory records the non-secret configuration needed to rebuild the
seven-day Gardener Shoot. The cluster is disposable; these files are the source
of truth.

Pinned releases:

- `open-telemetry/opentelemetry-demo` chart `0.41.0` (app `3.0.0`)
- `prometheus/prometheus-mcp` chart `0.18.0`
- Jaeger `2.19+` native `jaeger_mcp` extension

## Install

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install otel-demo open-telemetry/opentelemetry-demo \
  --namespace otel-demo --create-namespace \
  --version 0.41.0 \
  --values deploy/otel-demo/otel-demo-values.yaml \
  --server-side=true --force-conflicts \
  --wait --timeout 10m

helm upgrade --install prometheus-mcp \
  oci://ghcr.io/tjhop/charts/prometheus-mcp-server \
  --namespace otel-demo \
  --version 0.18.0 \
  --values deploy/otel-demo/prometheus-mcp-values.yaml \
  --wait --timeout 5m
```

Create `otel-demo-basic-auth` in the namespace without committing its
credentials. Then replace the three Shoot hostnames in
`deploy/otel-ops-ingress.yaml` and apply it:

```bash
kubectl --namespace otel-demo apply -f deploy/otel-ops-ingress.yaml
```

Gardener creates and renews the TLS secret declared by the Ingress. Wait until
the generated `Certificate` reports `Ready` before configuring clients.

The agent connects only to the authenticated remote MCP endpoints:

- `https://<jaeger-host>/mcp`
- `https://<prometheus-host>/mcp`

Supply the complete Basic Authorization value through
`MCP_BASIC_AUTH_HEADER`; never put credentials in URLs or committed YAML.
