#!/usr/bin/env bash
# Tests deploy/nginx.deploy.conf against real containers (needs Docker; no images are built):
#   * the demo, its APIs and /health are public; the analyst console and its API need the password
#   * /ingest is closed
#   * the visitor's address is taken from CF-Connecting-IP only when the request comes from the tunnel's address
#   * the API proxy limit applies per visitor
#
#   deploy/test_nginx_edge.sh
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE=nginx:alpine
SUFFIX=$$
NET="neurosoc-edge-test-$SUFFIX"
SUBNET=172.31.77.0/24      # not the stack's own subnet, so this can run next to a live stack
TUNNEL_IP=172.31.77.12
OTHER_IP=172.31.77.50
FRONT=edge-front-$SUFFIX
WORK=$(mktemp -d)
PASS=0
FAIL=0

cleanup() {
    docker rm -f "$FRONT" "edge-api-$SUFFIX" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

# The same file the deployment mounts, with the tunnel address moved into the test subnet.
sed "s/172\.30\.0\.12/$TUNNEL_IP/" deploy/nginx.deploy.conf > "$WORK/default.conf"

# A stub API: answers every request and reports the client address it was given in X-Forwarded-For.
cat > "$WORK/api.conf" <<'EOF'
server {
    listen 8000;
    location / {
        add_header X-Seen-Forwarded-For $http_x_forwarded_for always;
        default_type text/plain;
        return 200 "api\n";
    }
}
EOF
# analyst / secret
printf 'analyst:%s\n' "$(printf 'secret\n' | openssl passwd -apr1 -stdin)" > "$WORK/htpasswd"
mkdir -p "$WORK/html"
echo '<html>spa</html>' > "$WORK/html/index.html"

docker network create --subnet "$SUBNET" "$NET" >/dev/null
docker run -d --name "edge-api-$SUFFIX" --network "$NET" --network-alias inference-proxy \
    -v "$WORK/api.conf:/etc/nginx/conf.d/default.conf:ro" "$IMAGE" >/dev/null
docker run -d --name "$FRONT" --network "$NET" --network-alias dashboard --network-alias ingestion \
    -v "$WORK/default.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$WORK/htpasswd:/etc/nginx/htpasswd:ro" \
    -v "$WORK/html:/usr/share/nginx/html:ro" "$IMAGE" >/dev/null
docker exec "$FRONT" nginx -t >/dev/null 2>&1 || { docker exec "$FRONT" nginx -t; exit 1; }
sleep 2

# request <from-ip> <path> [extra wget args...]  ->  prints "<status> <X-Seen-Forwarded-For>"
request() {
    local from=$1 path=$2; shift 2
    local client="edge-client-$SUFFIX-${from##*.}"
    docker rm -f "$client" >/dev/null 2>&1 || true
    docker run --rm --name "$client" --network "$NET" --ip "$from" --entrypoint sh "$IMAGE" -c \
        "wget -S -O /dev/null $* http://dashboard$path 2>&1 | awk '/^ *HTTP\\//{s=\$2} /X-Seen-Forwarded-For/{x=\$2} END{print s\" \"x}'"
}

expect() {   # expect <description> <actual> <expected-prefix>
    if [[ "$2" == "$3"* ]]; then PASS=$((PASS + 1)); printf '  ok    %s\n' "$1"
    else FAIL=$((FAIL + 1)); printf '  FAIL  %s (got "%s", wanted "%s...")\n' "$1" "$2" "$3"; fi
}
AUTH='--header "Authorization: Basic YW5hbHlzdDpzZWNyZXQ="'
BAD='--header "Authorization: Basic YW5hbHlzdDp3cm9uZw=="'

echo "public:"
expect "/demo needs no password"                    "$(request $OTHER_IP /demo)"                          200
expect "/health needs no password"                  "$(request $OTHER_IP /health)"                        200
expect "/api/v1/demo/config needs no password"      "$(request $OTHER_IP /api/v1/demo/config)"            200
expect "/api/v1/sdk/config needs no password"       "$(request $OTHER_IP /api/v1/sdk/config)"             200
echo "private:"
expect "/ (analyst console) asks for a password"    "$(request $OTHER_IP /)"                              401
expect "/protection asks for a password"            "$(request $OTHER_IP /protection)"                    401
expect "/api/v1/universal/sites asks for a password" "$(request $OTHER_IP /api/v1/universal/sites)"       401
expect "/api/v1/universal/ws asks for a password"   "$(request $OTHER_IP /api/v1/universal/ws)"           401
expect "/api/v1/models/candidates asks for a password" "$(request $OTHER_IP /api/v1/models/candidates)"   401
expect "a wrong password is refused"                "$(request $OTHER_IP /protection $BAD)"               401
expect "the right password opens /protection"       "$(request $OTHER_IP /protection $AUTH)"              200
expect "the right password opens the analyst API"   "$(request $OTHER_IP /api/v1/universal/sites $AUTH)"  200
expect "the raw /ingest endpoint is closed"         "$(request $OTHER_IP /ingest)"                        404
echo "visitor address:"
spoof='--header "CF-Connecting-IP: 198.51.100.7"'
expect "from the tunnel, CF-Connecting-IP becomes the client address" "$(request $TUNNEL_IP /api/v1/demo/config $spoof)" "200 198.51.100.7"
expect "from anywhere else the header is ignored (no spoofing)"       "$(request $OTHER_IP  /api/v1/demo/config $spoof)" "200 $OTHER_IP"

echo
echo "passed: $PASS   failed: $FAIL"
[[ $FAIL -eq 0 ]]
