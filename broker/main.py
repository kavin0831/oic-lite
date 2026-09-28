"""
Broker (relay) service — the cloud-facing piece.

Plays the role of the OIC "Connectivity Agent" cloud endpoint: it never
touches the on-prem database directly. It only:
  1. Accepts a persistent outbound WebSocket connection FROM the agent
     (agent dials out, so no inbound firewall / VPN rule is needed on
     the EBS/on-prem network).
  2. Accepts REST query requests from client apps (the sample app).
  3. Forwards each query to the matching connected agent over its
     websocket, correlates the async response, and returns it to the
     caller.

Run:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8080
"""
import asyncio
import os
import time
import uuid
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header
from pydantic import BaseModel

# Shared secret the agent must present when it dials in.
# In production, issue a unique token per agent/group (like oic_CLIENT_SECRET).
AGENT_REGISTRATION_TOKEN = os.environ.get("AGENT_REGISTRATION_TOKEN", "change-me-agent-token")
# Shared secret client apps must present to submit queries.
CLIENT_API_KEY = os.environ.get("CLIENT_API_KEY", "change-me-client-key")

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))

app = FastAPI(title="OIC-Lite Broker")


class ConnectedAgent:
    def __init__(self, group: str, ws: WebSocket):
        self.group = group
        self.ws = ws
        self.connected_at = time.time()
        self.lock = asyncio.Lock()


class QueryRequest(BaseModel):
    group: str                 # which agent/group to route to (like agent_GROUP_IDENTIFIER)
    sql: str
    params: Optional[dict] = None
    max_rows: int = 500


class QueryResponse(BaseModel):
    ok: bool
    columns: Optional[list] = None
    rows: Optional[list] = None
    row_count: Optional[int] = None
    error: Optional[str] = None
    took_ms: Optional[int] = None


# group -> ConnectedAgent
AGENTS: Dict[str, ConnectedAgent] = {}
# request_id -> asyncio.Future waiting for the agent's reply
PENDING: Dict[str, asyncio.Future] = {}


@app.websocket("/ws/agent")
async def agent_socket(ws: WebSocket, token: str, group: str):
    if token != AGENT_REGISTRATION_TOKEN:
        await ws.close(code=4401)
        return

    await ws.accept()
    agent = ConnectedAgent(group, ws)
    AGENTS[group] = agent
    print(f"[broker] agent connected for group='{group}'")

    try:
        while True:
            msg = await ws.receive_json()
            # Agent sends back {"request_id": ..., "ok": bool, "columns":..., "rows":..., "error":...}
            req_id = msg.get("request_id")
            fut = PENDING.pop(req_id, None)
            if fut and not fut.done():
                fut.set_result(msg)
    except WebSocketDisconnect:
        print(f"[broker] agent disconnected for group='{group}'")
        if AGENTS.get(group) is agent:
            del AGENTS[group]


@app.post("/api/query", response_model=QueryResponse)
async def submit_query(req: QueryRequest, x_api_key: str = Header(default="")):
    if x_api_key != CLIENT_API_KEY:
        raise HTTPException(status_code=401, detail="invalid x-api-key")

    agent = AGENTS.get(req.group)
    if not agent:
        raise HTTPException(status_code=503, detail=f"no agent connected for group '{req.group}'")

    request_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    PENDING[request_id] = fut

    payload = {
        "request_id": request_id,
        "sql": req.sql,
        "params": req.params or {},
        "max_rows": req.max_rows,
    }

    start = time.time()
    try:
        async with agent.lock:
            await agent.ws.send_json(payload)
    except Exception as e:
        PENDING.pop(request_id, None)
        raise HTTPException(status_code=502, detail=f"failed to reach agent: {e}")

    try:
        result = await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        PENDING.pop(request_id, None)
        raise HTTPException(status_code=504, detail="agent did not respond in time")

    took_ms = int((time.time() - start) * 1000)

    if not result.get("ok"):
        return QueryResponse(ok=False, error=result.get("error", "unknown error"), took_ms=took_ms)

    return QueryResponse(
        ok=True,
        columns=result.get("columns"),
        rows=result.get("rows"),
        row_count=result.get("row_count"),
        took_ms=took_ms,
    )


@app.get("/api/agents")
async def list_agents():
    return {
        "connected_groups": [
            {"group": g, "connected_at": a.connected_at} for g, a in AGENTS.items()
        ]
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
