#!/usr/bin/env bash
# Deploy or update the public demo on this machine. Run by the self-hosted GitHub runner on a release tag,
# or by hand:   deploy/deploy.sh
#
# Steps: preflight -> remember the running images -> build -> start -> wait for health -> smoke tests ->
# roll back to the remembered images if anything fails. Needs the files created by
# `python3 deploy/preflight.py init` (default location ~/neurosoc-deploy, or $DEPLOY_HOME).
set -euo pipefail

cd "$(dirname "$0")/.."
DEPLOY_HOME="${DEPLOY_HOME:-$HOME/neurosoc-deploy}"
ENV_FILE="$DEPLOY_HOME/.env.deploy"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.deploy.yml)
IMAGES=(dashboard inference ingestion feature sandbox feedback retraining simulation-portal)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-480}"

log() { printf '\n== %s\n' "$*"; }

# One deployment at a time.
mkdir -p "$DEPLOY_HOME"
exec 9>"$DEPLOY_HOME/.deploy.lock"
flock -n 9 || { echo "another deployment is already running"; exit 1; }

log "Preflight"
python3 deploy/preflight.py --home "$DEPLOY_HOME" check

log "Remembering the running images (for rollback)"
for name in "${IMAGES[@]}"; do
    if docker image inspect "neurosoc/$name:deploy" >/dev/null 2>&1; then
        docker tag "neurosoc/$name:deploy" "neurosoc/$name:previous"
        echo "kept neurosoc/$name:deploy as :previous"
    fi
done

rollback() {
    log "ROLLING BACK to the previous images"
    local restored=0
    for name in "${IMAGES[@]}"; do
        if docker image inspect "neurosoc/$name:previous" >/dev/null 2>&1; then
            docker tag "neurosoc/$name:previous" "neurosoc/$name:deploy"
            restored=1
        fi
    done
    if [[ $restored -eq 1 ]]; then
        "${COMPOSE[@]}" up -d --no-build --remove-orphans || true
        echo "Previous version restarted. Logs: ${COMPOSE[*]} logs --tail=100"
    else
        echo "No previous images to restore (first deployment). Logs: ${COMPOSE[*]} logs --tail=100"
    fi
}

log "Building images"
"${COMPOSE[@]}" build --pull

log "Starting the stack"
"${COMPOSE[@]}" up -d --remove-orphans

wait_healthy() {
    local service=$1 deadline=$((SECONDS + HEALTH_TIMEOUT)) id state
    while (( SECONDS < deadline )); do
        id=$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)
        if [[ -n "$id" ]]; then
            state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")
            [[ "$state" == "healthy" || "$state" == "running" ]] && { echo "$service: $state"; return 0; }
            echo "$service: $state ..."
        fi
        sleep 5
    done
    echo "$service did not become healthy within ${HEALTH_TIMEOUT}s"
    return 1
}

# A request made from inside the dashboard container, i.e. what the tunnel sees. Prints the status line and the body.
probe() { "${COMPOSE[@]}" exec -T dashboard wget -S -O - "http://127.0.0.1$1" 2>&1 || true; }

smoke() {
    local failed=0 out
    out=$(probe /demo);                 grep -q ' 200 ' <<<"$out" && echo "ok  /demo is public"                     || { echo "FAIL /demo"; failed=1; }
    out=$(probe /health);               grep -q ' 200 ' <<<"$out" && echo "ok  /health is public"                   || { echo "FAIL /health"; failed=1; }
    out=$(probe /api/v1/demo/config);   grep -q '"connected":true' <<<"$out" && echo "ok  the demo is connected to its application" || { echo "FAIL the demo is not connected"; failed=1; }
    out=$(probe /protection);           grep -q ' 401 ' <<<"$out" && echo "ok  the analyst console asks for a password" || { echo "FAIL /protection is not protected"; failed=1; }
    out=$(probe /api/v1/universal/sites); grep -q ' 401 ' <<<"$out" && echo "ok  the analyst API asks for a password" || { echo "FAIL the analyst API is not protected"; failed=1; }
    return $failed
}

log "Waiting for the services"
if ! { wait_healthy inference && wait_healthy dashboard && wait_healthy cloudflared; }; then rollback; exit 1; fi

log "Smoke tests"
if ! smoke; then rollback; exit 1; fi

log "Cleaning up old images"
docker image prune -f --filter "until=168h" >/dev/null || true

host=$(grep '^PUBLIC_HOSTNAME=' "$ENV_FILE" | cut -d= -f2-)
log "Deployed. Public demo: https://$host/demo   (analyst console: https://$host/protection)"
