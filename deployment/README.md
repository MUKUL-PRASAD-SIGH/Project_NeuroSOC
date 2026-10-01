# Deploying the NeuroSOC public demo on your own PC

This sets up the NovaTrust demo and the NeuroSOC dashboard on a spare PC and puts them on the internet through a
**Cloudflare Tunnel**, so you open no ports on your router and your home IP address stays hidden. A **self-hosted
GitHub runner** on the same PC redeploys it when you push a release tag.

```
 visitor ──https──► Cloudflare ──tunnel──► cloudflared ─► nginx (dashboard) ─┬─► /demo, /api/v1/demo, /api/v1/sdk   public
                                                (your PC, Docker network)    ├─► /protection, /api/v1/universal ... password
                                                                             └─► inference API ─► Redis, Postgres, Kafka
```

## What this is, and is not

- It **is** a hardened *public demo*: nothing is published on the PC's network ports, the analyst console needs a password,
  the public APIs are rate-limited per visitor, secrets are generated fresh and kept outside the repository, and every start is
  preceded by automatic checks.
- It **is not** a production deployment. The NovaTrust demo cannot run with `APP_ENV=production` (the API refuses to start
  that way on purpose), so the stack runs in `local` mode and the analyst console is protected by a shared password at the
  edge instead of Keycloak. Do not put real customer data in it.
- The demo's state (applications and verdicts) lives in Redis and is recreated from the seed file when the stack restarts.
  The database is kept in a Docker volume.

## What you need

| | |
|---|---|
| The PC | Linux (Ubuntu or Debian recommended), about **12 GB RAM or more**, about **30 GB free disk**, always on, set not to sleep |
| Software | Docker Engine with **Compose v2.24 or newer**, `git`, `python3`, `openssl` |
| Cloudflare | A free Cloudflare account and a **domain whose DNS is on Cloudflare** (a subdomain such as `demo.yourdomain.com` is fine) |
| GitHub | Admin access to the repository (for the runner and the deployment approval) |

## One-time setup

### 1. Prepare the PC and get the code
```bash
sudo apt install -y git python3 openssl          # plus Docker Engine: https://docs.docker.com/engine/install/
sudo usermod -aG docker "$USER"                  # log out and in again afterwards
git clone git@github.com:MUKUL-PRASAD-SIGH/Project_NeuroSOC.git ~/neurosoc && cd ~/neurosoc
```
The repository must contain the trained model files under `models/` (they are tracked, so the clone has them).

### 2. Generate the secrets
```bash
python3 deployment/preflight.py init --hostname demo.yourdomain.com
```
This writes `~/neurosoc-deploy/` (outside the repository, mode 600): `.env.deploy` with a random password or key for
every setting below, `secrets/sites.json` with the demo application and **fresh keys**, and `secrets/htpasswd`. It prints the
**analyst login once**. Write it down; only a hash is stored. It refuses to overwrite an existing deployment
(`--force` makes new passwords, and an existing database volume would no longer accept the new database password).

### 3. Create the Cloudflare Tunnel
1. In the Cloudflare dashboard open **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, and name it.
2. On the "install connector" page copy the long **token** (the string after `--token` or `service install`).
3. Put it in `~/neurosoc-deploy/.env.deploy` as `CLOUDFLARE_TUNNEL_TOKEN=...` (or pass `--tunnel-token` to step 2).
4. Add a **Public hostname**: your subdomain and domain, **Service type HTTP**, **URL `dashboard:80`**. Cloudflare creates the
   DNS record and the HTTPS certificate. (WebSockets work by default.)

You do not install `cloudflared` on the PC itself: it runs as a container in the stack.

### 4. Check, then deploy
```bash
python3 deployment/preflight.py check      # must end with "OK: ready to deploy."
deployment/deploy.sh
```
The first build downloads and builds several large images (PyTorch among them), so it takes a while. `deploy.sh` waits for the
services to become healthy, runs smoke tests (the demo is public and connected, the console and its API ask for a password),
and **rolls back to the previous images automatically** if anything fails.

### 5. Look at it
- `https://demo.yourdomain.com/demo`: the NovaTrust app. Accept the privacy banner, chat with Nova AI, run a security test.
- `https://demo.yourdomain.com/protection`: asks for the analyst login, then shows the live verdicts from the demo.

## Deploying releases from GitHub

### Install the runner (once)
1. Repository **Settings → Actions → Runners → New self-hosted runner**, Linux. Follow the commands it shows, and give it the extra
   **label `neurosoc-pc`** when `./config.sh` asks.
2. Run it as a normal user that is in the `docker` group, as a service: `sudo ./svc.sh install && sudo ./svc.sh start`.
3. Settings → Environments → **New environment `production-pc`** → add yourself under **Required reviewers**, so every
   deployment waits for your approval.
4. Settings → Actions → General → **Fork pull request workflows**: require approval for all outside collaborators.
5. Only if you chose a different folder than `~/neurosoc-deploy`: add a repository **variable** `DEPLOY_HOME` with its path.

### Release
```bash
git tag v1.0.0 && git push origin v1.0.0
```
The **Deploy** workflow validates the deployment files on GitHub's servers, then waits for your approval, then the runner
on the PC runs `deployment/deploy.sh`. It refuses any commit that is not on `main`, and it never runs for pull requests.

> **Why those safeguards matter.** A self-hosted runner runs repository code on your PC, and membership of the `docker` group is
> equivalent to root. Anyone who can get code onto `main` and tag it can run commands on the PC. Keep `main` protected (pull
> request reviews required) and keep the runner off any machine that holds other secrets.

## Day to day

```bash
cd ~/neurosoc
alias nsc='docker compose --env-file ~/neurosoc-deploy/.env.deploy -f docker-compose.yml -f deployment/docker-compose.deploy.yml'
nsc ps                          # what is running and healthy
nsc logs --tail=100 inference   # logs (each service keeps at most 3 x 10 MB)
nsc restart inference           # restart one service
deployment/backup.sh                # database backup to ~/neurosoc-deploy/backups (the last 14 are kept)
deployment/test_nginx_edge.sh       # re-check the public/private rules against real containers
```
- **Update by hand:** `git pull && deployment/deploy.sh`. **Roll back by hand:** `docker tag neurosoc/<service>:previous neurosoc/<service>:deploy`
  for each of dashboard and inference, then `nsc up -d --no-build`.
- **Back up** `~/neurosoc-deploy/` (it holds `.env.deploy` and `secrets/`) somewhere safe and encrypted.
- **Change the analyst password:** `printf 'judge:%s\n' "$(openssl passwd -apr1)" > ~/neurosoc-deploy/secrets/htpasswd`
  (it prompts for the password), then `nsc restart dashboard`.
- **Stop everything:** `nsc down` (keeps the database volume; `down -v` deletes it).

## Checklist: the settings in `.env.deploy`

`preflight.py init` fills all of these; `preflight.py check` verifies them before every deployment.

| Setting | Meaning | Generated |
|---|---|---|
| `PUBLIC_HOSTNAME` | The hostname served by the tunnel; also the only allowed browser origin | you give it |
| `CLOUDFLARE_TUNNEL_TOKEN` | Connects the stack to your tunnel | you paste it |
| `DEPLOY_SECRETS_DIR` | Folder holding `sites.json` and `htpasswd` | yes |
| `APP_ENV=local`, `NEUROSOC_DEMO_MODE=true`, `ENABLE_UNIVERSAL_ENGINE=true`, `ENABLE_SIMULATION_API=false` | The public-demo mode (the bank simulation stays off) | fixed |
| `POSTGRES_PASSWORD`, `DATABASE_URL`, `KEYCLOAK_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` | Required by the compose file; Keycloak and Grafana are not started | random |
| `UNIVERSAL_HASH_SECRET`, `RATE_LIMIT_HASH_SECRET`, `SANDBOX_SERVICE_TOKEN` | Hash IP addresses; hash rate-limit keys; authenticate service-to-service calls | random, 32+ chars |
| `NOVATRUST_DEMO_SECRET_KEY` | The key the demo backend uses; must equal the key in `sites.json` | random |
| `NOVATRUST_DEMO_PASSWORD_ALICE/BOB/CAROL` | Passwords of the fictional bank users (unused while the simulation is off) | random |
| `CORS_ALLOWED_ORIGINS` | `https://<PUBLIC_HOSTNAME>` | yes |
| `ANTHROPIC_API_KEY` | Optional: lets Nova AI use Claude instead of the scripted planner | empty |
| `ALERT_WEBHOOK_URL`, `IPINFO_TOKEN`, `SMTP_HOST` | Optional integrations, off by default | empty |

## Security model

| Surface | Who can reach it | Protection |
|---|---|---|
| `/demo`, its static files, `/health` | Anyone | Read-only app; nothing sensitive |
| `/api/v1/sdk/*` | Anyone with the demo's *publishable* key from the registered origin | Site key + origin check, 20 requests a second per visitor |
| `/api/v1/demo/*` | Anyone | Acts only on a per-browser fake account; same rate limit |
| `/protection`, `/api/v1/universal/*`, alerts, models, WebSockets | Holders of the analyst login | nginx basic auth |
| `/ingest` | No one | Closed (404) |
| Redis, Kafka, Postgres, the API, the sandbox | Only containers on the Docker networks | No host ports published (checked by `preflight.py check`) |

Visitors' real addresses come from Cloudflare's `CF-Connecting-IP` header, trusted only from the tunnel container, so the
rate limit and the bot-farm detector work per visitor and the header cannot be spoofed (tested by `deployment/test_nginx_edge.sh`).

**Known limits.** One shared analyst password rather than per-person accounts. Traffic between the tunnel container and nginx, and
between services, is plain HTTP inside Docker. Redis and Kafka have no passwords because they are not reachable from outside.
The API runs in `local` mode, which is what lets the demo run. The seed keys of the demo application are generated for this
deployment; the sample keys in `sdk/sites.local.json` are never loaded.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `preflight check` says a setting is a placeholder | Re-run `init`, or edit the value in `.env.deploy` |
| `docker compose` complains about `!reset` | Compose is older than 2.24; upgrade Docker |
| The site shows a Cloudflare error 1033 or 502 | The tunnel is down or its hostname points elsewhere: `nsc logs cloudflared`; the public hostname must be `http://dashboard:80` |
| `/protection` loops on the password prompt | Wrong login; set a new one as shown under "Day to day" |
| The live feed says "Connecting" | The WebSocket is blocked: confirm WebSockets are on for the tunnel and that you passed the password prompt on `/protection` first |
| `/demo` says "Connect an application first" | `NOVATRUST_DEMO_SECRET_KEY` does not match `sites.json`: `preflight check` reports it |
| The runner never picks up a job | The runner is offline or lacks the `neurosoc-pc` label; the deploy job also waits for your approval |
| Deployment rolled back | Read the log of the failing step; `nsc logs --tail=200 inference dashboard` |

## What has and has not been verified

Verified by automated tests and real runs on a development machine: the secret generation and every `check` rule
(`tests/test_deploy_preflight.py`), the nginx rules against real containers (`deployment/test_nginx_edge.sh`: 15 checks,
including the spoofing case), that the rendered compose configuration publishes no ports, the seed file loading into the
API, and that the whole test suite passes.

**Not verified here:** a full first deployment on a PC with a real Cloudflare tunnel (it needs your account), the
self-hosted runner, and the automatic rollback path. Do the first deployment by hand (steps 1 to 5) before relying on
the runner, and try one tagged release with the approval gate on.
