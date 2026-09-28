"""
Sample App — a minimal client that proves an end-to-end query through the
broker to the on-prem agent, without any VPN.

Deployable to Render.com as its own web service, pointing at the broker's
public URL (also on Render, or anywhere reachable over HTTPS).
"""
import os
import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BROKER_URL = os.environ.get("BROKER_URL", "http://localhost:8080")
CLIENT_API_KEY = os.environ.get("CLIENT_API_KEY", "change-me-client-key")
DEFAULT_GROUP = os.environ.get("AGENT_GROUP_IDENTIFIER", "default-group")

app = FastAPI(title="OIC-Lite Sample App")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_group": DEFAULT_GROUP,
        "broker_url": BROKER_URL,
        "result": None,
    })


@app.post("/run", response_class=HTMLResponse)
async def run_query(request: Request, group: str = Form(...), sql: str = Form(...)):
    result = {"ok": False, "error": None, "columns": [], "rows": [], "took_ms": None}
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await client.post(
                f"{BROKER_URL}/api/query",
                json={"group": group, "sql": sql, "max_rows": 200},
                headers={"x-api-key": CLIENT_API_KEY},
            )
        if resp.status_code == 200:
            result.update(resp.json())
        else:
            result["error"] = f"HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        result["error"] = str(e)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_group": group,
        "broker_url": BROKER_URL,
        "sql": sql,
        "result": result,
    })


@app.get("/api/ping")
async def ping():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BROKER_URL}/api/agents")
    return resp.json()
