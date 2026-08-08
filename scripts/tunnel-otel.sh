#!/usr/bin/env sh
set -eu

KUBECONFIG_PATH="${SHOOT_KUBECONFIG:-/Users/example-user/Downloads/kubeconfig-gardenlogin--cloud--example-landscape.yaml}"
CONTEXT="${SHOOT_CONTEXT:-garden-cloud--example-landscape-external}"
NAMESPACE="${OTEL_NAMESPACE:-otel-demo}"

cleanup() {
  pids=$(jobs -p)
  if [ -n "${pids}" ]; then
    kill ${pids} 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

echo "Opening OTel tunnels through Kubernetes context: ${CONTEXT}"
echo "Prometheus: http://localhost:9090"
echo "Jaeger:     http://localhost:16686"
echo "OpenSearch: http://localhost:9200"

kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" -n "${NAMESPACE}" port-forward svc/prometheus 9090:9090 &
kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" -n "${NAMESPACE}" port-forward svc/jaeger 16686:16686 &
kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" -n "${NAMESPACE}" port-forward svc/opensearch 9200:9200 &

wait
