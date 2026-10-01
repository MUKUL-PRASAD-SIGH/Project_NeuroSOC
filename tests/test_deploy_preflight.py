"""deploy/preflight.py: what `init` writes, and that `check` catches the mistakes that would hurt a public deployment."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "deploy"))
sys.path.insert(0, str(REPO / "inference-service"))
sys.path.insert(0, str(REPO / "sdk" / "python"))

import preflight  # noqa: E402

HOST = "neurosoc-demo.dev"
TOKEN = base64.b64encode(json.dumps({"a": "acct", "t": "tunnel", "s": "secretsecret"}).encode()).decode()
needs_openssl = pytest.mark.skipif(not shutil.which("openssl"), reason="openssl is needed to hash the analyst password")
needs_docker = pytest.mark.skipif(not shutil.which("docker"), reason="docker is needed to render the compose file")


@pytest.fixture
def home(tmp_path):
    target = tmp_path / "deploy-home"
    assert preflight.main(["--home", str(target), "init", "--hostname", HOST, "--tunnel-token", TOKEN]) == 0
    return target


def edit_env(home: Path, **changes: str) -> None:
    lines = []
    for line in (home / ".env.deploy").read_text().splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{key}={changes[key]}" if key in changes else line)
    (home / ".env.deploy").write_text("\n".join(lines) + "\n")


def run_check(home: Path) -> tuple[int, str]:
    result = subprocess.run([sys.executable, str(REPO / "deploy" / "preflight.py"), "--home", str(home), "check", "--ci"],
                            capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


@needs_openssl
def test_init_writes_private_files_outside_the_repository(home, tmp_path):
    assert REPO not in home.parents
    for path in (home / ".env.deploy", home / "secrets" / "sites.json", home / "secrets" / "htpasswd"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
    assert stat.S_IMODE((home / "secrets").stat().st_mode) == 0o700


@needs_openssl
def test_generated_secrets_are_random_distinct_and_long(home):
    env = preflight.parse_env(home / ".env.deploy")
    secret_names = ["POSTGRES_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD", "GRAFANA_ADMIN_PASSWORD", "UNIVERSAL_HASH_SECRET",
                    "RATE_LIMIT_HASH_SECRET", "SANDBOX_SERVICE_TOKEN", "NOVATRUST_DEMO_SECRET_KEY"]
    values = [env[name] for name in secret_names]
    assert len(set(values)) == len(values)
    assert all(len(value) >= 24 for value in values)
    assert not any(re.search(r"(?i)change_?me|password123|changeme", value) for value in values)
    assert env["DATABASE_URL"].endswith("@postgres:5432/neuroshield") and env["POSTGRES_PASSWORD"] in env["DATABASE_URL"]


@needs_openssl
def test_the_public_demo_never_runs_in_production_mode(home):
    env = preflight.parse_env(home / ".env.deploy")
    assert env["APP_ENV"] == "local" and env["NEUROSOC_DEMO_MODE"] == "true" and env["ENABLE_SIMULATION_API"] == "false"
    assert env["CORS_ALLOWED_ORIGINS"] == f"https://{HOST}"


@needs_openssl
def test_the_seed_file_loads_into_the_api_with_fresh_keys_and_the_demo_agent(home):
    from api.routes.demo_agent import DEFAULT_AGENT
    from core.universal import MemoryKV, SiteRegistry

    assert preflight.DEMO_AGENT == DEFAULT_AGENT
    env = preflight.parse_env(home / ".env.deploy")
    registry = SiteRegistry(MemoryKV())
    assert registry.seed_from_file(str(home / "secrets" / "sites.json")) == 1
    site = registry.by_secret_key(env["NOVATRUST_DEMO_SECRET_KEY"])
    assert site is not None and site["demo"] is True and site["mode"] == "enforce"
    assert site["allowed_origins"] == [f"https://{HOST}"]
    assert not site["publishable_key"].startswith("pk_local")  # never the sample keys from sdk/sites.local.json


@needs_openssl
def test_htpasswd_holds_a_hash_not_the_password(home, capsys):
    line = (home / "secrets" / "htpasswd").read_text().strip()
    assert re.fullmatch(r"judge:\$apr1\$[./0-9A-Za-z]+\$[./0-9A-Za-z]{22}", line)


@needs_openssl
def test_init_refuses_to_overwrite_existing_secrets(home, capsys):
    assert preflight.main(["--home", str(home), "init", "--hostname", HOST, "--tunnel-token", TOKEN]) == 2
    assert preflight.main(["--home", str(home), "init", "--hostname", HOST, "--tunnel-token", TOKEN, "--force"]) == 0


@pytest.mark.parametrize("hostname", ["localhost", "not a host", "demo", "-bad.example.com", "a..b.com"])
def test_init_rejects_invalid_hostnames(tmp_path, hostname):
    assert preflight.main(["--home", str(tmp_path / "h"), "init", f"--hostname={hostname}", "--tunnel-token", TOKEN]) == 2


@needs_openssl
@needs_docker
def test_a_fresh_init_passes_the_check_including_the_compose_hardening(home):
    code, output = run_check(home)
    assert code == 0, output
    assert "no service publishes a host port" in output


@needs_openssl
def test_check_catches_a_placeholder_password(home):
    edit_env(home, POSTGRES_PASSWORD="CHANGE_ME_local_postgres_password")
    code, output = run_check(home)
    assert code == 1 and "POSTGRES_PASSWORD still holds a placeholder" in output


@needs_openssl
def test_check_catches_a_too_short_secret(home):
    edit_env(home, UNIVERSAL_HASH_SECRET="short")
    code, output = run_check(home)
    assert code == 1 and "UNIVERSAL_HASH_SECRET is too short" in output


@needs_openssl
def test_check_catches_loose_file_permissions(home):
    os.chmod(home / "secrets" / "htpasswd", 0o644)
    code, output = run_check(home)
    assert code == 1 and "htpasswd is readable by other users" in output


@needs_openssl
def test_check_catches_a_missing_tunnel_token_and_a_garbled_one(home):
    edit_env(home, CLOUDFLARE_TUNNEL_TOKEN="")
    assert "CLOUDFLARE_TUNNEL_TOKEN is empty" in run_check(home)[1]
    edit_env(home, CLOUDFLARE_TUNNEL_TOKEN="not-a-real-token-but-long-enough-xxxxxxxxxxxxxxxxxxxx")
    assert "is not a Cloudflare tunnel token" in run_check(home)[1]


@needs_openssl
def test_check_catches_demo_mode_in_production(home):
    edit_env(home, APP_ENV="production")
    code, output = run_check(home)
    assert code == 1 and "cannot be combined with APP_ENV=staging or production" in output


@needs_openssl
def test_check_catches_a_seed_file_that_does_not_match_the_demo_key(home):
    sites_path = home / "secrets" / "sites.json"
    sites = json.loads(sites_path.read_text())
    sites[0]["secret_key"] = "sk_" + "z" * 43
    sites_path.write_text(json.dumps(sites))
    os.chmod(sites_path, 0o600)
    code, output = run_check(home)
    assert code == 1 and "does not match NOVATRUST_DEMO_SECRET_KEY" in output


@needs_openssl
def test_check_catches_a_seed_file_for_another_hostname(home):
    sites_path = home / "secrets" / "sites.json"
    sites = json.loads(sites_path.read_text())
    sites[0]["allowed_origins"] = ["https://somewhere-else.dev"]
    sites_path.write_text(json.dumps(sites))
    os.chmod(sites_path, 0o600)
    assert "allowed_origins does not include" in run_check(home)[1]


def test_nginx_config_keeps_the_analyst_console_private_and_the_demo_public():
    text = (REPO / "deploy" / "nginx.deploy.conf").read_text()
    assert 'auth_basic "NeuroSOC analyst console";' in text and "auth_basic_user_file /etc/nginx/htpasswd;" in text
    for public in ("location = /demo", "location /api/v1/sdk/", "location /api/v1/demo/", "location = /health"):
        block = text[text.index(public):]
        assert "auth_basic off;" in block.split("}")[0], public
    for private in ("location /api/v1/universal/ws", "location /api/ {", "location / {"):
        block = text[text.index(private):].split("\n    }")[0]
        assert "auth_basic off" not in block, private
    assert "location = /ingest { return 404; }" in text
    assert "set_real_ip_from 172.30.0.12;" in text and "real_ip_header CF-Connecting-IP;" in text


def test_compose_overlay_publishes_no_ports_and_uses_the_pinned_tunnel_image():
    text = (REPO / "deploy" / "docker-compose.deploy.yml").read_text()
    assert re.search(r"cloudflare/cloudflared:\d{4}\.\d+\.\d+", text), "pin the tunnel image to a version"
    assert "ports: !reset []" in text and not re.search(r"^\s+ports:\s*\n\s+-", text, re.M)
    assert "ipv4_address: ${API_PROXY_CLOUDFLARED_IP:-172.30.0.12}" in text
