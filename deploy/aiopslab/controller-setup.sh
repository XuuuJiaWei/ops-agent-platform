#!/usr/bin/env bash
# Bootstrap the AIOpsLab controller on a fresh Linux VM (or WSL2).
# Idempotent: safe to re-run.
#
# Requires: root or sudo, network access to GitHub/PyPI.
# After this script, edit aiopslab/config.yml and point kubectl at the target
# cluster (see deploy/aiopslab/README.md).

set -euo pipefail

REPO_URL="${AIOPSLAB_REPO_URL:-https://github.com/microsoft/AIOpsLab.git}"
INSTALL_DIR="${AIOPSLAB_INSTALL_DIR:-$HOME/AIOpsLab}"

echo "==> Installing system deps (python3.11, poetry, kubectl, helm)"
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev \
  curl git openssh-client datamash libssl-dev libz-dev unzip
curl -sSL https://install.python-poetry.org | python3.11 -
export PATH="$HOME/.local/bin:$PATH"

# kubectl (latest stable)
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm -f kubectl

# helm
curl -fsSL -o /tmp/get-helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod +x /tmp/get-helm.sh && sudo /tmp/get-helm.sh

echo "==> Cloning AIOpsLab (with aiopslab-applications submodule)"
if [ ! -d "$INSTALL_DIR/.git" ]; then
  git clone --recurse-submodules "$REPO_URL" "$INSTALL_DIR"
else
  git -C "$INSTALL_DIR" pull --ff-only
  git -C "$INSTALL_DIR" submodule update --init --recursive
fi

echo "==> poetry install"
cd "$INSTALL_DIR"
poetry env use python3.11
poetry install
eval "$(poetry env activate)"

echo "==> Config"
if [ ! -f aiopslab/config.yml ]; then
  cp aiopslab/config.yml.example aiopslab/config.yml
  echo "Wrote aiopslab/config.yml — edit k8s_host / k8s_user / ssh_key_path as needed."
fi

echo "==> Done. Next steps:"
echo "    cd $INSTALL_DIR"
echo "    eval \$(poetry env activate)"
echo "    kubectl config use-context <your-cluster-context>"
echo "    python cli.py   # or: poetry run pytest tests/integration/smoke_test.py -v -s"
