from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
import os
import json
import asyncio
import httpx

# ═══════════════════════════════════════════
# 🦊 Zeabur MCP - HTTP/SSE 双模式
# ═══════════════════════════════════════════
#
# 部署到 Zeabur，RikkaHub 添加 MCP 连接:
#   Streamable HTTP: https://你的域名/mcp
#   SSE (备用):      https://你的域名/sse
#
# 环境变量:
#   ZEABUR_TOKEN - Zeabur API Token (必填)
#   PORT          - 端口 (默认 8765)
#

ZEABUR_TOKEN = os.environ.get("ZEABUR_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8765))

GRAPHQL_URL = "https://api.zeabur.com/graphql"

mcp = FastMCP("Zeabur")

# ── GraphQL Helper ──

async def gql(query: str, variables: dict = None) -> dict:
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


def fmt(obj, title="") -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    return f"{title}{text}" if title else text


# ═══════════════════════════════════════════
# MCP 工具
# ═══════════════════════════════════════════

@mcp.tool()
async def list_projects() -> str:
    """列出所有 Zeabur 项目，返回项目ID、名称、区域和环境ID。"""
    query = """
    query ListProjects {
      projects {
        edges {
          node {
            _id
            name
            region { code name }
            environments { _id name }
          }
        }
      }
    }
    """
    data = await gql(query)
    if "error" in data:
        return f"❌ {data['error']}"
    projects = data.get("projects", {}).get("edges", [])
    if not projects:
        return "📭 没有找到任何项目"
    lines = []
    for p in projects:
        n = p["node"]
        envs = ", ".join(e["name"] for e in n.get("environments", []))
        lines.append(f"📦 {n['name']} (ID: {n['_id']})")
        lines.append(f"   区域: {n['region']['name']} | 环境: {envs}")
    return "\n".join(lines)


@mcp.tool()
async def list_services(project_id: str) -> str:
    """列出指定项目下的所有服务。project_id 从 list_projects 获取。"""
    query = """
    query ListServices($projectID: ObjectID!) {
      services(projectID: $projectID) {
        edges {
          node { _id name template createdAt status }
        }
      }
    }
    """
    data = await gql(query, {"projectID": project_id})
    if "error" in data:
        return f"❌ {data['error']}"
    services = data.get("services", {}).get("edges", [])
    if not services:
        return "📭 项目下没有服务"
    lines = []
    for s in services:
        n = s["node"]
        lines.append(f"🔧 {n['name']} (ID: {n['_id']})")
        lines.append(f"   模板: {n.get('template','N/A')} | 状态: {n.get('status','N/A')} | 创建: {n.get('createdAt','N/A')[:10]}")
    return "\n".join(lines)


@mcp.tool()
async def get_service(service_id: str) -> str:
    """获取服务详情，包括域名、Dockerfile、最近部署记录。"""
    query = """
    query GetService($id: ObjectID!) {
      service(_id: $id) {
        _id name template createdAt status
        domains { _id domain status isGenerated }
        spec { source { dockerfile } }
        deployments { _id status createdAt startedAt finishedAt }
      }
    }
    """
    data = await gql(query, {"id": service_id})
    if "error" in data:
        return f"❌ {data['error']}"
    svc = data.get("service", {})
    if not svc:
        return "📭 未找到该服务"
    lines = [f"🔧 {svc['name']} (ID: {svc['_id']})"]
    lines.append(f"   状态: {svc.get('status')} | 模板: {svc.get('template')}")
    domains = svc.get("domains", [])
    if domains:
        for d in domains:
            lines.append(f"   🌐 {d['domain']} ({d['status']})")
    deploys = svc.get("deployments", [])
    if deploys:
        d = deploys[0]
        lines.append(f"   📋 最近部署: {d['status']} @ {d.get('createdAt','N/A')[:19]}")
        lines.append(f"      部署ID: {d['_id']}")
    return "\n".join(lines)


@mcp.tool()
async def get_deployments(service_id: str, environment_id: str) -> str:
    """获取服务的部署历史。service_id 从 list_services 获取，environment_id 从 list_projects 获取。"""
    query = """
    query GetDeployments($serviceId: ObjectID!, $environmentId: ObjectID!) {
      deployments(serviceID: $serviceId, environmentID: $environmentId) {
        edges {
          node { _id status createdAt startedAt }
        }
      }
    }
    """
    data = await gql(query, {"serviceId": service_id, "environmentId": environment_id})
    if "error" in data:
        return f"❌ {data['error']}"
    deps = data.get("deployments", {}).get("edges", [])
    if not deps:
        return "📭 没有部署记录"
    lines = []
    for d in deps:
        n = d["node"]
        lines.append(f"📋 {n['_id']}")
        lines.append(f"   状态: {n['status']} | 创建: {n.get('createdAt','N/A')[:19]} | 开始: {n.get('startedAt','N/A')[:19]}")
    return "\n".join(lines)


@mcp.tool()
async def get_build_logs(deployment_id: str) -> str:
    """获取指定部署的构建日志（依赖安装、编译等）。deployment_id 从 get_deployments 获取。"""
    query = """
    query BuildLogs($deploymentId: ObjectID!) {
      buildLogs(deploymentID: $deploymentId) {
        message
        timestamp
      }
    }
    """
    data = await gql(query, {"deploymentId": deployment_id})
    if "error" in data:
        return f"❌ {data['error']}"
    logs = data.get("buildLogs", [])
    if not logs:
        return "📭 没有构建日志"
    lines = [f"📋 构建日志 (部署: {deployment_id})"]
    for entry in logs[-200:]:
        ts = entry.get("timestamp", "")[:19]
        msg = entry.get("message", "")
        lines.append(f"  [{ts}] {msg}")
    if len(logs) > 200:
        lines.append(f"  ... 共 {len(logs)} 条，只显示最后200条")
    return "\n".join(lines)


@mcp.tool()
async def get_runtime_logs(service_id: str, environment_id: str, project_id: str, deployment_id: str = "") -> str:
    """获取服务运行时日志（服务运行输出）。参数从 list_projects/list_services 获取。可选 deployment_id 筛选特定部署。"""
    query = """
    query GetRuntimeLogs(
      $serviceId: ObjectID!
      $environmentId: ObjectID!
      $projectId: ObjectID!
      $deploymentId: ObjectID
    ) {
      runtimeLogs(
        serviceID: $serviceId
        environmentID: $environmentId
        projectID: $projectId
        deploymentID: $deploymentId
      ) {
        message
        timestamp
      }
    }
    """
    variables = {
        "serviceId": service_id,
        "environmentId": environment_id,
        "projectId": project_id,
    }
    if deployment_id:
        variables["deploymentId"] = deployment_id
    data = await gql(query, variables)
    if "error" in data:
        return f"❌ {data['error']}"
    logs = data.get("runtimeLogs", [])
    if not logs:
        return "📭 没有运行时日志"
    lines = [f"📋 运行时日志 (服务: {service_id})"]
    for entry in logs[-200:]:
        ts = entry.get("timestamp", "")[:19]
        msg = entry.get("message", "")
        lines.append(f"  [{ts}] {msg}")
    if len(logs) > 200:
        lines.append(f"  ... 共 {len(logs)} 条，只显示最后200条")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# FastAPI + SSE / Streamable HTTP
# ═══════════════════════════════════════════

app = FastAPI(title="Zeabur MCP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SSE ---
_sse_transport = SseServerTransport("/messages")

async def sse_endpoint(request: Request):
    async def sse_asgi_app(scope, receive, send):
        async with _sse_transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            await mcp._mcp_server.run(
                read_stream, write_stream,
                mcp._mcp_server.create_initialization_options()
            )
    return sse_asgi_app

async def messages_endpoint(request: Request):
    return _sse_transport.handle_post_message

app.add_route("/sse", sse_endpoint, methods=["GET"])
app.add_route("/messages", messages_endpoint, methods=["POST"])


# --- Streamable HTTP ---
@app.post("/mcp")
async def handle_mcp(request: Request):
    body = await request.json()
    server = mcp._mcp_server

    class StreamResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {"content-type": "text/event-stream", "cache-control": "no-cache", "connection": "keep-alive"}
            self._chunks = []

        async def send(self, chunk):
            if isinstance(chunk, str):
                chunk = chunk.encode()
            self._chunks.append(chunk)

        async def send_header(self, name, value):
            self.headers[name.lower()] = value

    class StreamRequest:
        def __init__(self, body, headers):
            self.body = body
            self.headers = headers
            self.method = "POST"

    from mcp.server.streamable_http import StreamableHTTPServerTransport
    transport = StreamableHTTPServerTransport()
    stream_resp = StreamResponse()
    stream_req = StreamRequest(body, dict(request.headers))

    read_stream = asyncio.StreamReader()
    read_stream.feed_data(json.dumps(body))
    read_stream.feed_eof()

    await server.connect(transport)
    await transport.handle_request(stream_req, stream_resp, read_stream)

    return Response(content=b"".join(stream_resp._chunks), media_type="text/event-stream")


@app.get("/health")
async def health():
    status = "ok" if ZEABUR_TOKEN else "missing_token"
    return JSONResponse({"status": status, "token_set": bool(ZEABUR_TOKEN)})


# ═══════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print(f"🦊 Zeabur MCP Server")
    print(f"   SSE:   http://localhost:{PORT}/sse")
    print(f"   HTTP:  http://localhost:{PORT}/mcp")
    print(f"   Token: {'✅ 已设置' if ZEABUR_TOKEN else '❌ 未设置'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, timeout_keep_alive=120)
