#!/usr/bin/env bash
# Back up the database to $DEPLOY_HOME/backups (compressed, last 14 kept).   deploy/backup.sh
# The demo's live state (applications and verdicts) is in Redis, which is not persisted: it is recreated from the
# seed file when the stack restarts. What is worth keeping is the database and the deployment home itself
# (.env.deploy and secrets/): copy that folder somewhere safe, encrypted.
set -euo pipefail

cd "$(dirname "$0")/.."
DEPLOY_HOME="${DEPLOY_HOME:-$HOME/neurosoc-deploy}"
COMPOSE=(docker compose --env-file "$DEPLOY_HOME/.env.deploy" -f docker-compose.yml -f deploy/docker-compose.deploy.yml)
mkdir -p "$DEPLOY_HOME/backups"
umask 077
out="$DEPLOY_HOME/backups/neuroshield-$(date +%Y%m%d-%H%M%S).sql.gz"
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$out"
[[ -s "$out" ]] || { echo "backup is empty, removing it"; rm -f "$out"; exit 1; }
ls -1t "$DEPLOY_HOME"/backups/neuroshield-*.sql.gz | tail -n +15 | xargs -r rm -f
echo "wrote $out"
