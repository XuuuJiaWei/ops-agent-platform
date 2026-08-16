"""Real (non-flag) fault problems for the OpenTelemetry demo workload.

AIOpsLab's built-in astronomy-shop problems all use ``OtelFaultInjector``,
which toggles a feature flag in the ``flagd-config`` ConfigMap. That couples
the fault injection surface with the agent's observation surface: an agent
with kubectl access can read the ConfigMap and see the answer.

These problems keep the same ``AstronomyShop`` workload but inject faults at
the symptom layer through Chaos Mesh (pod failure, network loss, ...). The
agent can only observe the effects (restarts, latency, error rates), never
the injection itself.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, ClassVar

import yaml
from aiopslab.generators.fault.base import FaultInjector
from aiopslab.generators.fault.inject_symp import SymptomFaultInjector
from aiopslab.orchestrator.evaluators.quantitative import is_exact_match, is_subset
from aiopslab.orchestrator.tasks.localization import LocalizationTask
from aiopslab.service.apps.astronomy_shop import AstronomyShop
from aiopslab.service.helm import Helm
from aiopslab.service.kubectl import KubeCtl
from aiopslab.session import SessionItem

# The OpenTelemetry demo chart labels pods with app.kubernetes.io/name
# (verified on the target cluster), while AIOpsLab's built-in injectors
# hardcode the DeathStarBench label `io.kompose.service`.
OTEL_LABEL_KEY = "app.kubernetes.io/name"


class OtelSymptomInjector(SymptomFaultInjector):
    """Chaos Mesh injector adapted for the OpenTelemetry demo workload.

    Changes vs. the AIOpsLab original:
    * selectors use the OTel demo label key instead of ``io.kompose.service``;
    * experiment YAML is written to the platform temp dir (the original
      hardcodes ``/tmp``, which breaks on Windows);
    * cleanup deletes the Chaos experiment by resource name, so it works even
      after the temp file is gone;
    * an already-deployed Chaos Mesh release is reused instead of reinstall.
    """

    _EXPERIMENT_KIND: ClassVar[dict[str, tuple[str, str]]] = {
        "pod-failure": ("PodChaos", "pod-failure-experiment"),
        "pod-kill": ("PodChaos", "pod-kill"),
        "container-kill": ("PodChaos", "container-kill"),
        "network-loss": ("NetworkChaos", "loss"),
        "network-delay": ("NetworkChaos", "delay"),
    }

    def __init__(self, namespace: str) -> None:
        # SymptomFaultInjector.__init__ installs Chaos Mesh unconditionally;
        # installing over an existing release only prints an error. Reuse the
        # already-deployed release when present.
        if Helm.exists_release("chaos-mesh", "chaos-mesh"):
            FaultInjector.__init__(self, namespace)
            self.namespace = namespace
            self.kubectl = KubeCtl()
        else:
            super().__init__(namespace)

    def create_chaos_experiment(
        self, experiment_yaml: dict, experiment_name: str
    ) -> None:
        chaos_yaml_path = Path(tempfile.gettempdir()) / f"{experiment_name}.yaml"
        chaos_yaml_path.write_text(yaml.safe_dump(experiment_yaml, sort_keys=False))
        # --validate=false skips the OpenAPI schema download, which times out
        # intermittently on managed clusters and would silently drop the fault.
        command = f"kubectl apply -f {chaos_yaml_path.as_posix()} --validate=false"
        result = self.kubectl.exec_command(command)
        print(f"Applied {experiment_name} chaos experiment: {result}")

    def delete_chaos_experiment(self, experiment_name: str) -> None:
        kind, name = self._EXPERIMENT_KIND[experiment_name]
        command = f"kubectl delete {kind.lower()} {name} -n {self.namespace} --ignore-not-found"
        result = self.kubectl.exec_command(command)
        print(f"Cleaned up {experiment_name} chaos experiment: {result}")

    @staticmethod
    def _selector(
        microservices: list[str], namespaces: list[str] | None = None
    ) -> dict:
        selector: dict[str, Any] = {
            "labelSelectors": {OTEL_LABEL_KEY: ", ".join(microservices)}
        }
        if namespaces:
            selector["namespaces"] = namespaces
        return selector

    def inject_pod_failure(
        self, microservices: list[str], duration: str = "1800s"
    ) -> None:
        experiment = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {"name": "pod-failure-experiment", "namespace": self.namespace},
            "spec": {
                "action": "pod-failure",
                "mode": "one",
                "duration": duration,
                "selector": self._selector(microservices),
            },
        }
        self.create_chaos_experiment(experiment, "pod-failure")

    def inject_pod_kill(
        self, microservices: list[str], duration: str = "1800s"
    ) -> None:
        # Same semantic as AIOpsLab: use action pod-failure so the pod is not
        # immediately recreated and the fault stays observable during the run.
        experiment = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {"name": "pod-kill", "namespace": self.namespace},
            "spec": {
                "action": "pod-failure",
                "mode": "one",
                "duration": duration,
                "selector": self._selector(microservices),
            },
        }
        self.create_chaos_experiment(experiment, "pod-kill")

    def inject_network_loss(
        self, microservices: list[str], duration: str = "1800s"
    ) -> None:
        experiment = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "NetworkChaos",
            "metadata": {"name": "loss", "namespace": self.namespace},
            "spec": {
                "action": "loss",
                "mode": "one",
                "duration": duration,
                "selector": self._selector(microservices, namespaces=[self.namespace]),
                "loss": {"loss": "99", "correlation": "100"},
            },
        }
        self.create_chaos_experiment(experiment, "network-loss")

    def inject_network_delay(
        self,
        microservices: list[str],
        duration: str = "1800s",
        latency: str = "10s",
        jitter: str = "0ms",
    ) -> None:
        experiment = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "NetworkChaos",
            "metadata": {"name": "delay", "namespace": self.namespace},
            "spec": {
                "action": "delay",
                "mode": "one",
                "duration": duration,
                "selector": self._selector(microservices, namespaces=[self.namespace]),
                "delay": {"latency": latency, "correlation": "100", "jitter": jitter},
            },
        }
        self.create_chaos_experiment(experiment, "network-delay")

    def inject_container_kill(self, microservice: str, containers: list[str]) -> None:
        experiment = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {"name": "container-kill", "namespace": self.namespace},
            "spec": {
                "action": "container-kill",
                "mode": "one",
                "duration": "1800s",
                "selector": self._selector([microservice]),
                "containerNames": containers,
            },
        }
        self.create_chaos_experiment(experiment, "container-kill")


class AstronomyShopChaosLocalization(LocalizationTask):
    """Localize a Chaos Mesh fault injected into one Astronomy Shop service."""

    # Chaos faults never modify the app itself; the bridge may keep a warm
    # deployment across runs instead of deleting/redeploying each time.
    PERSISTENT: ClassVar[bool] = True

    def __init__(
        self,
        faulty_service: str,
        fault_type: str,
        duration: str = "1800s",
    ) -> None:
        self.app = AstronomyShop()
        self.namespace = self.app.namespace
        self.faulty_service = faulty_service
        self.fault_type = fault_type
        self.duration = duration
        self.injector = OtelSymptomInjector(namespace=self.namespace)
        LocalizationTask.__init__(self, self.app)

    def start_workload(self) -> None:
        print("== Start Workload ==")
        print("Workload skipped since AstronomyShop has a built-in load generator.")

    def inject_fault(self) -> None:
        print(f"== Fault Injection: {self.fault_type} on {self.faulty_service} ==")
        self.injector._inject(
            fault_type=self.fault_type,
            microservices=[self.faulty_service],
            duration=self.duration,
        )

    def recover_fault(self) -> None:
        print(f"== Fault Recovery: {self.fault_type} ==")
        self.injector._recover(self.fault_type)

    def eval(self, soln: Any, trace: list[SessionItem], duration: float) -> dict:
        print("== Evaluation ==")

        if soln is None:
            print("Solution is None")
            self.add_result("Localization Accuracy", 0.0)
            self.results["success"] = False
            self.results["is_subset"] = False
            super().eval(soln, trace, duration)
            return self.results

        is_exact = is_exact_match(soln, self.faulty_service)
        is_sub = is_subset([self.faulty_service], soln)

        if is_exact:
            accuracy = 100.0
            print(f"Exact match: {soln} | Accuracy: {accuracy}%")
        elif is_sub:
            accuracy = (len([self.faulty_service]) / len(soln)) * 100.0
            print(f"Subset match: {soln} | Accuracy: {accuracy:.2f}%")
        else:
            accuracy = 0.0
            print(f"No match: {soln} | Accuracy: {accuracy}%")

        self.add_result("Localization Accuracy", accuracy)
        super().eval(soln, trace, duration)

        self.results["success"] = is_exact or (is_sub and len(soln) == 1)
        self.results["is_subset"] = is_sub

        return self.results


# Problem ids registered into the bridge's Orchestrator at startup.
CUSTOM_PROBLEM_REGISTRY = {
    "astronomy_shop_payment_pod_kill-localization-1": lambda: (
        AstronomyShopChaosLocalization(faulty_service="payment", fault_type="pod_kill")
    ),
    "astronomy_shop_payment_network_loss-localization-1": lambda: (
        AstronomyShopChaosLocalization(
            faulty_service="payment", fault_type="network_loss"
        )
    ),
}
