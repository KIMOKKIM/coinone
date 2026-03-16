#!/usr/bin/env bash
#
# deploy_to_ubuntu.sh
# Usage: ./deploy_to_ubuntu.sh <user@host> <remote_path>
#
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 user@host /path/to/deploy/coinone"
  exit 1
fi

REMOTE=$1
REMOTE_PATH=$2

echo "Packaging and deploying to ${REMOTE}:${REMOTE_PATH}"

# create archive
ARCHIVE=coinone_deploy.tar.gz
git archive --format=tar HEAD | gzip > /tmp/${ARCHIVE}

echo "Uploading archive..."
scp /tmp/${ARCHIVE} ${REMOTE}:/tmp/${ARCHIVE}

echo "Extracting on remote..."
ssh ${REMOTE} "mkdir -p ${REMOTE_PATH} && tar -xzf /tmp/${ARCHIVE} -C ${REMOTE_PATH} && rm /tmp/${ARCHIVE}"

echo "Setting up virtualenv and installing deps..."
ssh ${REMOTE} "cd ${REMOTE_PATH} && python3 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt && playwright install chromium"

echo "Installing systemd unit (requires sudo)..."
ssh ${REMOTE} "sudo cp ${REMOTE_PATH}/deploy/coinone-trader.service.template /etc/systemd/system/coinone-trader.service && sudo systemctl daemon-reload && sudo systemctl enable coinone-trader.service && sudo systemctl restart coinone-trader.service"

echo "Deployment complete."

