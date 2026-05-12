#!/usr/bin/env bash
# Deploy ha-echocheck to a Home Assistant instance via SSH
#
# Usage: ./scripts/deploy.sh [user@host] [port]
#   user@host: SSH target (default: pete@192.168.1.183)
#   port:      SSH port   (default: 22)

set -euo pipefail

HOST="${1:-pete@192.168.1.183}"
PORT="${2:-22}"
REMOTE_DIR="/config/custom_components/ha_echocheck"
COMPONENT_DIR="custom_components/ha_echocheck"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SSH_OPTS="-p ${PORT}"

echo "==> Deploying ha_echocheck to ${HOST}:${PORT}"
echo "    Source: ${PROJECT_DIR}/${COMPONENT_DIR}"
echo "    Target: ${HOST}:${REMOTE_DIR}"

# Ensure remote directories exist
ssh ${SSH_OPTS} "${HOST}" "mkdir -p ${REMOTE_DIR}/translations"

# Deploy via tar-over-SSH (HAOS lacks rsync/sftp-server)
tar -C "${PROJECT_DIR}" -czf - "${COMPONENT_DIR}" \
  | ssh ${SSH_OPTS} "${HOST}" "tar -C /config/custom_components -xzf - --strip-components=1"

echo "==> Files deployed. Restarting HA core..."
ssh ${SSH_OPTS} "${HOST}" "bash -l -c 'ha core restart'"

echo "==> Done. Monitor logs with:"
echo "    ssh -p ${PORT} ${HOST} 'ha core logs -f' | grep -i echocheck"
