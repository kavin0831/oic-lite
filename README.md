# OIC-Lite — VPN-free query agent for Oracle EBS

A minimal, self-owned equivalent of the Oracle OIC Connectivity Agent
pattern: an on-prem agent dials **out** to a cloud broker, so a cloud app
can run SQL against your on-prem/EBS database without any inbound
firewall rule or VPN.

```
[ sample_app ] --HTTPS--> [ broker (Render.com) ] --WSS (agent-initiated)--> [ agent (on-prem, next to EBS DB) ] --JDBC/oracledb--> [ Oracle EBS DB ]
```

- **broker/** — public cloud service. Accepts the agent's outbound websocket
  connection and exposes `POST /api/query` for client apps.
- **agent/** — runs on a machine that already has network access to the EBS
  DB (same box, or same LAN). Connects out to the broker, executes SQL,
  streams results back. Read-only by default (`ALLOW_WRITE=0`).
- **sample_app/** — tiny web UI to type SQL and see results come back
  through the broker, proving the round trip works.

## 1. Deploy the broker + sample app to Render.com

1. Push this `oic-lite/` folder to a git repo.
2. In Render: New → Blueprint → point at the repo → it reads `render.yaml`
   and creates both `oic-lite-broker` and `oic-lite-sample-app`.
3. Render auto-generates `AGENT_REGISTRATION_TOKEN` and `CLIENT_API_KEY` for
   the broker — copy them from the broker service's Environment tab.
4. On `oic-lite-sample-app`, set:
   - `BROKER_URL = https://oic-lite-broker.onrender.com`
   - `CLIENT_API_KEY = <same value as broker's CLIENT_API_KEY>`
5. Redeploy the sample app.

## 2. Run the agent on-prem, via Portainer

The agent has no inbound ports — it only dials out to the broker and to
the EBS DB — so it's a good fit for a container on whatever host Portainer
manages that already has network access to EBS.

**Option A — Portainer "Stacks" (recommended, docker-compose based):**
1. In Portainer: **Stacks → Add stack**.
2. Paste the contents of [`agent/docker-compose.yml`](agent/docker-compose.yml),
   or point it at this repo (Git repository method) with `agent/docker-compose.yml`
   as the compose path.
3. Edit the `environment:` values before deploying:
   - `BROKER_URL` → `wss://oic-lite-broker.onrender.com` (your broker's Render URL, `wss://` not `https://`)
   - `AGENT_REGISTRATION_TOKEN` → copy from the broker service's env vars on Render
   - `DB_DSN`, `DB_USER`, `DB_PASSWORD` → your EBS DB connection details
4. Deploy the stack. Portainer builds the image from `agent/Dockerfile` and
   starts the container with `restart: unless-stopped`.

**Option B — plain `docker run` (if you'd rather not use a compose stack):**
```bash
cd agent
docker build -t oic-lite-agent .
docker run -d --name oic-lite-agent --restart unless-stopped \
  -e BROKER_URL=wss://oic-lite-broker.onrender.com \
  -e AGENT_GROUP_IDENTIFIER=EBS-PROD-1 \
  -e AGENT_REGISTRATION_TOKEN=<broker's AGENT_REGISTRATION_TOKEN> \
  -e DB_DSN="ebshost.internal:1521/EBSDB" \
  -e DB_USER=ebs_readonly_user \
  -e DB_PASSWORD=******** \
  oic-lite-agent
```
You can then import/manage that same container from Portainer's Containers view.

**Verify it's connected:** check the container logs (Portainer → Containers →
oic-lite-agent → Logs) for `[agent] connected. waiting for queries.`, then
`GET https://oic-lite-broker.onrender.com/api/agents` should list the group.

## 3. Query from the sample app

Open the sample app's Render URL, set the agent group to match
`AGENT_GROUP_IDENTIFIER`, type SQL (e.g. `SELECT * FROM ap_invoices_all
WHERE ROWNUM <= 10`), and run it. The request flows sample_app → broker →
agent → EBS DB and the result flows back the same path — no VPN involved.

## Security notes (read before using with real EBS credentials)

- Set strong, unique values for `AGENT_REGISTRATION_TOKEN` and
  `CLIENT_API_KEY` — never leave the defaults in `main.py`/`agent.py`.
- The agent blocks INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/REVOKE/MERGE
  by default (`ALLOW_WRITE=0`). Only flip `ALLOW_WRITE=1` if you deliberately
  want write access, and prefer a dedicated read-only DB account regardless.
- This is a demo/starter, not a hardened product: for real production use,
  add per-client scoping (not just a shared API key), TLS-pinned or mTLS
  agent auth, SQL allow-listing/parameter binding enforcement, rate limiting,
  and audit logging before pointing it at a real EBS instance.
