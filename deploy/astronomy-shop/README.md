# Rebuild the Astronomy Shop Shoot

This directory records the non-secret configuration needed to rebuild the
seven-day Gardener Shoot. The cluster is disposable; these files are the source
of truth.

Pinned releases:

- `open-telemetry/opentelemetry-demo` chart `0.41.0` (app `3.0.0`)
- `prometheus/prometheus-mcp` chart `0.18.0`
- `ingress-nginx/ingress-nginx` chart `4.15.1` (app `1.15.1`)
- Jaeger `2.19+` native `jaeger_mcp` extension

The cluster needs a two-node worker pool: the full stack requests ~98% of a
single node's memory, so the cluster autoscaler adds a second node during the
first install. Expect a few pods to sit `Pending` until it joins.

## Install

The Ingress needs an nginx controller, but the Gardener `nginxIngress` shoot
addon is unsupported on Kubernetes 1.33+ (the dashboard refuses to enable it on
this 1.35 shoot). Install the controller directly instead; it provisions a
cloud LoadBalancer and registers a default `nginx` IngressClass:

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.ingressClassResource.default=true \
  --wait --timeout 5m
```

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
  --namespace astronomy-shop --create-namespace \
  --version 0.41.0 \
  --values deploy/astronomy-shop/values.yaml \
  --server-side=true --force-conflicts \
  --wait --timeout 10m

helm upgrade --install prometheus-mcp \
  oci://ghcr.io/tjhop/charts/prometheus-mcp-server \
  --namespace astronomy-shop \
  --version 0.18.0 \
  --values deploy/astronomy-shop/prometheus-mcp-values.yaml \
  --wait --timeout 5m
```

Create `astronomy-shop-basic-auth` in the namespace without committing its
credentials — an nginx basic-auth secret holds an `apr1`-hashed line:

```bash
kubectl create secret generic astronomy-shop-basic-auth --namespace astronomy-shop \
  --from-literal=auth="otel:$(openssl passwd -apr1 "$OTEL_BASIC_AUTH_PASSWORD")"
```

The committed `otel-ops-ingress.yaml` keeps `*.example.com` placeholders as the
reusable source of truth. Substitute this Shoot's domain (find it via
`kubectl -n kube-system get cm shoot-info -o jsonpath='{.data.domain}'`) at
apply time rather than editing the file:

```bash
DOMAIN=$(kubectl -n kube-system get cm shoot-info -o jsonpath='{.data.domain}')
sed "s/\.example\.com/.${DOMAIN}/g" deploy/astronomy-shop/otel-ops-ingress.yaml \
  | kubectl --namespace astronomy-shop apply -f -
```

Gardener creates and renews the TLS secret declared by the Ingress. Wait until
the generated `Certificate` reports `Ready` before configuring clients. DNS for
the hosts resolves to the ingress LoadBalancer; no `DNSEntry` object appears in
the namespace.

The agent connects only to the authenticated remote MCP endpoints:

- `https://<jaeger-host>/mcp`
- `https://<prometheus-host>/mcp`

Supply the complete Basic Authorization value through
`MCP_BASIC_AUTH_HEADER`; never put credentials in URLs or committed YAML.
