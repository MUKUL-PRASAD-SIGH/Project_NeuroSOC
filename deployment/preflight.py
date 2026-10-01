#!/usr/bin/env python3
"""Preflight for the public-demo deployment: create the secrets, then check everything before each start.

    python3 deployment/preflight.py init  --hostname demo.example.org [--tunnel-token TOKEN]
    python3 deployment/preflight.py check [--ci]

`init` writes, under the deployment home (default ~/neurosoc-deploy, or $DEPLOY_HOME), outside the repository:

    .env.deploy          every setting and secret the stack needs, generated and random (mode 600)
    secrets/sites.json   the demo application with fresh keys, loaded by the API on start
    secrets/htpasswd     the analyst console login (nginx basic auth)

It prints the analyst password once; it is stored only as a hash. `check` verifies the files, the values, the
host (Docker, memory, disk) and the rendered compose configuration, including that no service publishes a port.
Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "deployment/docker-compose.deploy.yml")
HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
PLACEHOLDER_RE = re.compile(r"(?i)(change_?me|your[-_]|example\.|placeholder|<[^>]*>|^xxx)")
USER_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")

# The demo application: same agent the dashboard wizard registers (api/routes/demo_agent.py DEFAULT_AGENT).
DEMO_AGENT = {
    "agent_id": "novatrust-agent",
    "name": "Nova AI",
    "tools": ["get_balance", "get_transactions", "get_portfolio", "create_transfer", "cancel_transfer"],
    "sensitive_actions": ["token.transfer"],
    "authorized_resources": ["treasury"],
}
# Settings that must hold a real, non-placeholder value, and the shortest acceptable length for the secret ones.
REQUIRED = ("PUBLIC_HOSTNAME", "CLOUDFLARE_TUNNEL_TOKEN", "POSTGRES_PASSWORD", "DATABASE_URL", "KEYCLOAK_ADMIN_PASSWORD",
            "GRAFANA_ADMIN_PASSWORD", "UNIVERSAL_HASH_SECRET", "RATE_LIMIT_HASH_SECRET", "SANDBOX_SERVICE_TOKEN",
            "NOVATRUST_DEMO_SECRET_KEY", "DEPLOY_SECRETS_DIR")
MIN_SECRET_LENGTH = {"POSTGRES_PASSWORD": 24, "KEYCLOAK_ADMIN_PASSWORD": 24, "GRAFANA_ADMIN_PASSWORD": 24,
                     "UNIVERSAL_HASH_SECRET": 32, "RATE_LIMIT_HASH_SECRET": 32, "SANDBOX_SERVICE_TOKEN": 32,
                     "NOVATRUST_DEMO_SECRET_KEY": 32}


def deploy_home(value: str | None = None) -> Path:
    return Path(value or os.environ.get("DEPLOY_HOME") or Path.home() / "neurosoc-deploy").expanduser().resolve()


def token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def apr1_hash(password: str) -> str:
    """An nginx-compatible htpasswd hash, from openssl (the password goes in on stdin, never on the command line)."""
    if not shutil.which("openssl"):
        raise SystemExit("openssl is required to hash the analyst password (install it and retry).")
    result = subprocess.run(["openssl", "passwd", "-apr1", "-stdin"], input=password + "\n", capture_output=True, text=True, check=True)
    return result.stdout.strip()


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


# ── init ────────────────────────────────────────────────────────────────────────────────────────
def build_env(hostname: str, tunnel_token: str, secrets_dir: Path) -> dict[str, str]:
    postgres_password = token(24)
    return {
        "COMPOSE_PROJECT_NAME": "neurosoc",
        "COMPOSE_PROFILES": "phase11plus",          # the dashboard on top of the core services
        "PUBLIC_HOSTNAME": hostname,
        "CLOUDFLARE_TUNNEL_TOKEN": tunnel_token,
        "DEPLOY_SECRETS_DIR": str(secrets_dir),
        "APP_ENV": "local",
        "ENABLE_UNIVERSAL_ENGINE": "true",
        "NEUROSOC_DEMO_MODE": "true",
        "ENABLE_SIMULATION_API": "false",
        "OIDC_REQUIRED": "false",
        "POSTGRES_PASSWORD": postgres_password,
        "DATABASE_URL": f"postgresql://ns_user:{postgres_password}@postgres:5432/neuroshield",
        "KEYCLOAK_ADMIN_PASSWORD": token(24),
        "GRAFANA_ADMIN_PASSWORD": token(24),
        "UNIVERSAL_HASH_SECRET": token(32),
        "RATE_LIMIT_HASH_SECRET": token(32),
        "SANDBOX_SERVICE_TOKEN": token(32),
        "NOVATRUST_DEMO_PASSWORD_ALICE": token(16),
        "NOVATRUST_DEMO_PASSWORD_BOB": token(16),
        "NOVATRUST_DEMO_PASSWORD_CAROL": token(16),
        "CORS_ALLOWED_ORIGINS": f"https://{hostname}",
        "ALERT_WEBHOOK_URL": "",
        "IPINFO_TOKEN": "",
        "SMTP_HOST": "",
        "ANTHROPIC_API_KEY": "",   # optional: lets Nova AI use Claude instead of the scripted planner
    }


def build_sites(hostname: str, secret_key: str) -> list[dict]:
    return [{
        "site_id": "novatrust-public-demo",
        "tenant_id": "local",
        "name": "NovaTrust",
        "publishable_key": "pk_" + token(24),
        "secret_key": secret_key,
        "allowed_origins": [f"https://{hostname}"],
        "mode": "enforce",
        "preset": "novatrust",
        "app_type": "both",
        "url": f"https://{hostname}/demo",
        "demo": True,
        "agents": [dict(DEMO_AGENT)],
    }]


def init(home: Path, hostname: str, analyst_user: str, tunnel_token: str | None, force: bool) -> int:
    hostname = hostname.strip().lower()
    if not HOST_RE.match(hostname):
        print(f"error: {hostname!r} is not a valid public hostname (for example demo.example.org)", file=sys.stderr)
        return 2
    if not USER_RE.match(analyst_user):
        print("error: the analyst user must be 3 to 32 lowercase letters, digits, '.', '_' or '-'", file=sys.stderr)
        return 2
    env_path, secrets_dir = home / ".env.deploy", home / "secrets"
    if env_path.exists() and not force:
        print(f"error: {env_path} already exists; use --force to replace it (this makes new passwords and keys,", file=sys.stderr)
        print("       and an existing database volume would no longer accept the new database password).", file=sys.stderr)
        return 2
    if tunnel_token is None and sys.stdin.isatty():
        tunnel_token = getpass.getpass("Cloudflare Tunnel token (Enter to add it later in .env.deploy): ").strip() or None
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secrets_dir, 0o700)

    env = build_env(hostname, tunnel_token or "", secrets_dir)
    demo_secret = "sk_" + token(32)                      # the API connects the demo with this key (also in sites.json)
    env["NOVATRUST_DEMO_SECRET_KEY"] = demo_secret
    password = token(12)
    write_private(env_path, "# Generated by deployment/preflight.py init. Never commit this file.\n"
                  + "\n".join(f"{key}={value}" for key, value in env.items()) + "\n")
    write_private(secrets_dir / "sites.json", json.dumps(build_sites(hostname, demo_secret), indent=2) + "\n")
    write_private(secrets_dir / "htpasswd", f"{analyst_user}:{apr1_hash(password)}\n")

    print(f"Created {env_path} and {secrets_dir}/ (mode 600, outside the repository).\n")
    print("Analyst console login (shown once, stored only as a hash):")
    print(f"    user:     {analyst_user}")
    print(f"    password: {password}\n")
    if not tunnel_token:
        print("The Cloudflare Tunnel token is empty: put it in CLOUDFLARE_TUNNEL_TOKEN in .env.deploy (deployment/README.md, step 3).")
    print("Next: python3 deployment/preflight.py check")
    return 0


# ── check ───────────────────────────────────────────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def ok(self, message: str) -> None:
        self.items.append(("ok", message))

    def warn(self, message: str) -> None:
        self.items.append(("warn", message))

    def error(self, message: str) -> None:
        self.items.append(("ERROR", message))

    @property
    def failed(self) -> bool:
        return any(level == "ERROR" for level, _ in self.items)

    def print(self) -> None:
        for level, message in self.items:
            print(f"  [{level:5s}] {message}")


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def check_files(env: dict[str, str], env_path: Path, report: Report) -> None:
    if os.name == "posix" and _mode(env_path) & 0o077:
        report.error(f"{env_path} is readable by other users (mode {_mode(env_path):o}); run: chmod 600 {env_path}")
    else:
        report.ok(f"{env_path.name} exists and is private")
    for key in REQUIRED:
        value = env.get(key, "")
        if not value:
            report.error(f"{key} is empty")
        elif PLACEHOLDER_RE.search(value):
            report.error(f"{key} still holds a placeholder value")
        elif len(value) < MIN_SECRET_LENGTH.get(key, 1):
            report.error(f"{key} is too short ({len(value)} characters; at least {MIN_SECRET_LENGTH[key]})")
    if not any(item[0] == "ERROR" and item[1].split()[0] in REQUIRED for item in report.items):
        report.ok("all required settings are present, non-placeholder and long enough")

    host = env.get("PUBLIC_HOSTNAME", "")
    if host and not HOST_RE.match(host):
        report.error(f"PUBLIC_HOSTNAME {host!r} is not a valid public hostname")
    if env.get("NEUROSOC_DEMO_MODE", "").lower() == "true" and env.get("APP_ENV", "") in {"staging", "production"}:
        report.error("NEUROSOC_DEMO_MODE=true cannot be combined with APP_ENV=staging or production (the API refuses to start)")
    if env.get("ENABLE_SIMULATION_API", "false").lower() == "true":
        report.warn("ENABLE_SIMULATION_API=true exposes the bank-simulation endpoints; leave it false on a public host")

    raw = env.get("CLOUDFLARE_TUNNEL_TOKEN", "")
    if raw:
        try:
            decoded = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
            if not {"a", "t", "s"} <= set(decoded):
                raise ValueError("missing fields")
            report.ok("Cloudflare tunnel token has the expected structure")
        except Exception:  # noqa: BLE001 - any failure means the token was mis-pasted
            report.error("CLOUDFLARE_TUNNEL_TOKEN is not a Cloudflare tunnel token (copy the long token from the tunnel's install command)")

    secrets_dir = Path(env.get("DEPLOY_SECRETS_DIR", ""))
    sites_path, htpasswd = secrets_dir / "sites.json", secrets_dir / "htpasswd"
    for path in (sites_path, htpasswd):
        if not path.is_file():
            report.error(f"{path} is missing")
        elif os.name == "posix" and _mode(path) & 0o077:
            report.error(f"{path} is readable by other users; run: chmod 600 {path}")
    if sites_path.is_file():
        try:
            site = json.loads(sites_path.read_text())[0]
            if site.get("secret_key") != env.get("NOVATRUST_DEMO_SECRET_KEY"):
                report.error("sites.json secret_key does not match NOVATRUST_DEMO_SECRET_KEY (the demo could not connect)")
            elif f"https://{host}" not in site.get("allowed_origins", []):
                report.error(f"sites.json allowed_origins does not include https://{host}")
            elif str(site.get("secret_key", "")).startswith("sk_local"):
                report.error("sites.json holds a sample key from the repository; run init again")
            else:
                report.ok("sites.json matches the demo key and the public hostname")
        except (ValueError, IndexError, KeyError):
            report.error("sites.json is not a valid seed file")
    if htpasswd.is_file():
        if re.match(r"^[a-z][a-z0-9_.-]+:\$apr1\$", htpasswd.read_text()):
            report.ok("htpasswd has an analyst login")
        else:
            report.error("htpasswd has no valid analyst line")


def meminfo_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return None
    return None


def check_host(home: Path, report: Report) -> None:
    docker = shutil.which("docker")
    if not docker:
        report.error("docker is not installed")
        return
    version = subprocess.run([docker, "compose", "version", "--short"], capture_output=True, text=True)
    match = re.match(r"v?(\d+)\.(\d+)", version.stdout.strip())
    if version.returncode or not match:
        report.error("docker compose (v2) is not available")
    elif (int(match.group(1)), int(match.group(2))) < (2, 24):
        report.error(f"docker compose {version.stdout.strip()} is too old; the overlay needs 2.24 or newer")
    else:
        report.ok(f"docker compose {version.stdout.strip()}")
    if subprocess.run([docker, "info"], capture_output=True).returncode:
        report.error("the Docker daemon is not running or this user cannot reach it")
    memory = meminfo_gb()
    if memory is not None:
        (report.error if memory < 8 else report.warn if memory < 12 else report.ok)(f"{memory:.1f} GB RAM (the stack wants about 12 GB or more)")
    free = shutil.disk_usage(home if home.exists() else Path.home()).free / 1024 ** 3
    (report.error if free < 15 else report.warn if free < 30 else report.ok)(f"{free:.0f} GB free disk (images and data want about 30 GB)")


def check_compose(env_path: Path, report: Report) -> None:
    command = ["docker", "compose", "--env-file", str(env_path)]
    for name in COMPOSE_FILES:
        command += ["-f", str(REPO / name)]
    result = subprocess.run(command + ["config", "--format", "json"], capture_output=True, text=True, cwd=REPO)
    if result.returncode:
        report.error("docker compose config failed: " + (result.stderr.strip().splitlines() or ["unknown error"])[-1])
        return
    services = json.loads(result.stdout)["services"]
    published = sorted(name for name, service in services.items() if service.get("ports"))
    if published:
        report.error("these services publish host ports: " + ", ".join(published) + " (only the tunnel should reach the stack)")
    else:
        report.ok("no service publishes a host port")
    for name in ("cloudflared", "dashboard", "inference"):
        if name not in services:
            report.error(f"service {name} is missing from the rendered configuration")
    dashboard = services.get("dashboard", {})
    if not any("nginx.deploy.conf" in str(v.get("source", "")) for v in dashboard.get("volumes", [])):
        report.error("the dashboard is not using deployment/nginx.deploy.conf")
    else:
        report.ok("dashboard uses the deployment nginx configuration")
    environment = services.get("inference", {}).get("environment", {})
    if environment.get("APP_ENV") != "local" or environment.get("NEUROSOC_DEMO_MODE") != "true":
        report.error("inference is not configured for the public demo (APP_ENV=local, NEUROSOC_DEMO_MODE=true)")


def check(home: Path, ci: bool) -> int:
    env_path = home / ".env.deploy"
    report = Report()
    if not env_path.is_file():
        print(f"error: {env_path} not found; run: python3 deployment/preflight.py init --hostname <your hostname>", file=sys.stderr)
        return 2
    env = parse_env(env_path)
    print(f"Preflight for {env_path}")
    check_files(env, env_path, report)
    if not ci:
        check_host(home, report)
    if shutil.which("docker"):
        check_compose(env_path, report)
    elif ci:
        report.warn("docker not available; skipped the compose checks")
    report.print()
    print("\nFAILED: fix the errors above before deploying." if report.failed else "\nOK: ready to deploy.")
    return 1 if report.failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", help="deployment home (default: $DEPLOY_HOME or ~/neurosoc-deploy)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="generate the secrets and settings")
    p_init.add_argument("--hostname", required=True, help="the public hostname served by the tunnel, e.g. demo.example.org")
    p_init.add_argument("--analyst-user", default="judge", help="user name for the analyst console (default: judge)")
    p_init.add_argument("--tunnel-token", help="the Cloudflare Tunnel token (prompted for when omitted)")
    p_init.add_argument("--force", action="store_true", help="replace existing files")
    p_check = sub.add_parser("check", help="verify the files, values, host and compose configuration")
    p_check.add_argument("--ci", action="store_true", help="skip the host checks (RAM, disk, daemon)")
    args = parser.parse_args(argv)
    home = deploy_home(args.home)
    if args.command == "init":
        return init(home, args.hostname, args.analyst_user, args.tunnel_token, args.force)
    return check(home, args.ci)


if __name__ == "__main__":
    raise SystemExit(main())
