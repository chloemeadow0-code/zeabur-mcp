import os
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.routing import Mount

ZEABUR_TOKEN = os.environ.get("ZEABUR_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8765))
GRAPHQL_URL = "https://api.zeabur.com/graphql"

mcp = FastMCP("Zeabur")


# ── GraphQL Helper ──────────────────────────────────────────────────────────

async def gql(query: str, variables: dict = None) -> dict:
    if not ZEABUR_TOKEN:
        return {"error": "ZEABUR_TOKEN 未设置"}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ZEABUR_TOKEN}",
    }
    body = {"query": query}
    if variables:
        body["variables"] = variables
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GRAPHQL_URL, json=body, headers=headers)
        data = resp.json()
        if "errors" in data:
            return {"error": data["errors"]}
        return data.get("data", {})


# ── MCP 工具 ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_projects() -> str:
    """列出所有 Zeabur 项目，返回 project_id、项目名和环境列表（含 environment_id）。
    查日志前先调用此工具获取 project_id 和 environment_id。"""
    data = await gql("""
        query {
          projects(skip: 0, limit: 100) {
            edges {
              node {
                _id
                name
                environments { _id name }
              }
            }
          }
        }
    """)
    if "error" in data:
        return f"❌ {data['error']}"
    edges = data.get("projects", {}).get("edges", [])
    if not edges:
        return "📭 没有项目"
    lines = []
    for e in edges:
        n = e["node"]
        lines.append(f"📦 {n['name']}")
        lines.append(f"   project_id: {n['_id']}")
        for env in n.get("environments", []):
            lines.append(f"   🌍 环境: {env['name']}  environment_id: {env['_id']}")
    return "\n".join(lines)


@mcp.tool()
async def list_services(project_id: str) -> str:
    """列出指定项目下的所有服务，返回服务名和 service_id。"""
    data = await gql("""
        query ListServices($projectID: ObjectID!) {
          services(projectID: $projectID) {
            edges {
              node { _id name }
            }
          }
        }
    """, {"projectID": project_id})
    if "error" in data:
        return f"❌ {data['error']}"
    edges = data.get("services", {}).get("edges", [])
    if not edges:
        return "📭 没有服务"
    lines = []
    for e in edges:
        n = e["node"]
        lines.append(f"🔧 {n['name']}  service_id: {n['_id']}")
    return "\n".join(lines)


@mcp.tool()
async def get_runtime_logs(service_id: str, environment_id: str) -> str:
    """获取服务运行时日志（启动输出、报错等）。
    service_id 从 list_services 获取，environment_id 从 list_projects 获取。"""
    data = await gql("""
        query RuntimeLogs($serviceID: ObjectID!, $environmentID: ObjectID!) {
          runtimeLogs(serviceID: $serviceID, environmentID: $environmentID) {
            message
            timestamp
          }
        }
    """, {"serviceID": service_id, "environmentID": environment_id})
    if "error" in data:
        return f"❌ {data['error']}"
    logs = data.get("runtimeLogs", [])
    if not logs:
        return "📭 没有运行时日志"
    lines = [f"📋 Runtime 日志（共 {len(logs)} 条，显示最后 200 条）"]
    for entry in logs[-200:]:
        ts = (entry.get("timestamp") or "")[:19]
        lines.append(f"[{ts}] {entry.get('message', '')}")
    return "\n".join(lines)


@mcp.tool()
async def get_deployments(service_id: str, environment_id: str) -> str:
    """获取服务的部署列表（含 deployment_id 和状态）。
    查 build 日志前需先调用此工具获取 deployment_id。"""
    data = await gql("""
        query Deployments($serviceID: ObjectID!, $environmentID: ObjectID!) {
          deployments(serviceID: $serviceID, environmentID: $environmentID) {
            edges {
              node { _id status createdAt }
            }
          }
        }
    """, {"serviceID": service_id, "environmentID": environment_id})
    if "error" in data:
        return f"❌ {data['error']}"
    edges = data.get("deployments", {}).get("edges", [])
    if not edges:
        return "📭 没有部署记录"
    lines = ["📋 部署列表"]
    for e in edges:
        n = e["node"]
        ts = (n.get("createdAt") or "")[:19]
        lines.append(f"[{ts}] {n['status']}  deployment_id: {n['_id']}")
    return "\n".join(lines)


@mcp.tool()
async def get_build_logs(deployment_id: str) -> str:
    """获取指定部署的构建日志（依赖安装、编译过程）。
    deployment_id 从 get_deployments 获取。"""
    data = await gql("""
        query BuildLogs($deploymentID: ObjectID!) {
          buildLogs(deploymentID: $deploymentID) {
            message
            timestamp
          }
        }
    """, {"deploymentID": deployment_id})
    if "error" in data:
        return f"❌ {data['error']}"
    logs = data.get("buildLogs", [])
    if not logs:
        return "📭 没有构建日志"
    lines = [f"📋 Build 日志（共 {len(logs)} 条，显示最后 200 条）"]
    for entry in logs[-200:]:
        ts = (entry.get("timestamp") or "")[:19]
        lines.append(f"[{ts}] {entry.get('message', '')}")
    return "\n".join(lines)


# ── FastAPI + 传输层 ──────────────────────────────────────────────────────────

app = FastAPI(title="Zeabur MCP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# SSE
_sse = SseServerTransport("/messages/")
app.router.routes.append(Mount("/messages", app=_sse.handle_post_message))

@app.get("/sse")
async def sse_handler(request: Request):
    async with _sse.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),
        )

# Streamable HTTP
app.mount("/mcp", mcp.streamable_http_app())


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "token_set": bool(ZEABUR_TOKEN),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
