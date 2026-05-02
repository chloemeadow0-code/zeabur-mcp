from fastapi import Request, Response
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
import os, json, asyncio
import httpx

# ═══════════════════════════════════════════
# 🔧 Zeabur MCP Server - HTTP/SSE 双模式
# ═══════════════════════════════════════════
#
# 部署到 Zeabur，RikkaHub 添加 MCP 连接:
#   Streamable HTTP: https://你的域名/mcp
#   SSE: https://你的域名/sse
#
# 环境变量:
#   ZEABUR_TOKEN - Zeabur API Token (必填)
#   PORT         - 端口 (默认 8765)
#

ZEABUR_TOKEN = os.environ.get("ZEABUR_TOKEN", "").strip()
GRAPHQL_URL = "https://api.zeabur.com/graphql"
PORT = int(os.environ.get("PORT", 8765))

mcp = FastMCP("ZeaburMCP")


# ═══════════════════════════════════════════
# GraphQL 查询封装
# ═══════════════════════════════════════════

async def gql(query: str, variables: dict = None) -> dict:
    if not ZEABUR_TOKEN:
        return {"error": "未配置 ZEABUR_TOKEN"}
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GRAPHQL_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {ZEABUR_TOKEN}",
                },
            )
            data = resp.json()
            if data.get("errors"):
                return {"error": data["errors"]}
            return data.get("data", {})
    except Exception as e:
        return {"error": str(e)}


def fmt(data: dict) -> str:
    """格式化输出，去掉嵌套太深的结构"""
    return json.dumps(data, indent=2, ensure_ascii=False)


def extract_logs(logs_data: dict) -> str:
    """从 GraphQL 返回中提取日志，格式化为可读文本"""
    lines = []
    for key in ("buildLogs", "runtimeLogs"):
        entries = logs_data.get(key, [])
        if isinstance(entries, list):
            for entry in entries:
                ts = entry.get("timestamp", "")
                msg = entry.get("message", "")
                if msg:
                    lines.append(f"{ts}  {msg}")
    if not lines:
        return json.dumps(logs_data, indent=2, ensure_ascii=False)
    return "\n".join(lines)


# ═══════════════════════════════════════════
# MCP 工具
# ═══════════════════════════════════════════

@mcp.tool()
async def list_projects() -> str:
    """列出所有 Zeabur 项目，包含项目ID、名称、区域和环境ID"""
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
    """列出指定项目下的所有服务

    参数:
      project_id: 项目ID (从 list_projects 获取)
    """
    query = """
    query ListServices($projectID: ObjectID!) {
      services(projectID: $projectID) {
        edges {
          node {
            _id
            name
            template
            createdAt
            status
          }
        }
      }
    }
    """
    data = await gql(query, {"projectID": project_id})
    if "error" in data:
        return f"❌ {data['error']}"
    services = data.get("services", {}).get("edges", [])
    if not services:
        return "📭 该项目下没有服务"
    lines = []
    for s in services:
        n = s["node"]
        lines.append(f"🖥️ {n['name']} (ID: {n['_id']})")
        lines.append(f"   状态: {n['status']} | 模板: {n['template']} | 创建: {n['createdAt']}")
    return "\n".join(lines)


@mcp.tool()
async def get_service(service_id: str) -> str:
    """获取服务的详细信息，包含域名、Dockerfile、最近部署

    参数:
      service_id: 服务ID (从 list_services 获取)
    """
    query = """
    query GetService($id: ObjectID!) {
      service(_id: $id) {
        _id
        name
        template
        status
        createdAt
        domains { _id domain status isGenerated }
        deployments(_first: 3) { _id status createdAt }
      }
    }
    """
    data = await gql(query, {"id": service_id})
    if "error" in data:
        return f"❌ {data['error']}"
    svc = data.get("service", {})
    if not svc:
        return "📭 服务不存在"
    lines = [f"🖥️ {svc['name']} (ID: {svc['_id']})"]
    lines.append(f"状态: {svc['status']} | 模板: {svc['template']}")
    domains = svc.get("domains", [])
    if domains:
        lines.append(f"域名:")
        for d in domains:
            lines.append(f"  - {d['domain']} ({d['status']})")
    deploys = svc.get("deployments", [])
    if deploys:
        lines.append(f"最近部署:")
        for dp in deploys[:3]:
            lines.append(f"  - {dp['_id'][:12]}... {dp['status']} {dp['createdAt']}")
    return "\n".join(lines)


@mcp.tool()
async def get_deployments(service_id: str, environment_id: str) -> str:
    """获取服务的部署记录列表

    参数:
      service_id: 服务ID
      environment_id: 环境ID (从 list_projects 获取)
    """
    query = """
    query GetDeployments($serviceId: ObjectID!, $environmentId: ObjectID!) {
      deployments(serviceID: $serviceId, environmentID: $environmentId) {
        edges {
          node {
            _id
            status
            createdAt
            startedAt
            finishedAt
          }
        }
      }
    }
    """
    data = await gql(query, {
        "serviceId": service_id,
        "environmentId": environment_id,
    })
    if "error" in data:
        return f"❌ {data['error']}"
    deploys = data.get("deployments", {}).get("edges", [])
    if not deploys:
        return "📭 没有部署记录"
    lines = []
    for d in deploys:
        n = d["node"]
        lines.append(f"🚀 {n['_id']}  [{n['status']}]  {n['createdAt']}")
        if n.get("finishedAt"):
            lines.append(f"   完成: {n['finishedAt']}")
    return "\n".join(lines)


@mcp.tool()
async def get_build_logs(deployment_id: str) -> str:
    """查看指定部署的构建日志（依赖安装、编译等）

    参数:
      deployment_id: 部署ID (从 get_deployments 获取)
    """
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
    logs = extract_logs(data)
    if not logs.strip() or logs.strip() == "{}":
        return "📭 没有构建日志"
    return f"📋 构建日志 ({deployment_id}):\n\n{logs}"


@mcp.tool()
async def get_runtime_logs(
    service_id: str,
    project_id: str,
    environment_id: str,
    deployment_id: str = "",
) -> str:
    """查看服务的运行时日志（服务运行输出、报错等）

    参数:
      service_id: 服务ID
      project_id: 项目ID
      environment_id: 环境ID
      deployment_id: 部署ID (可选，用于筛选特定部署的日志)
    """
    variables = {
        "serviceId": service_id,
        "projectId": project_id,
        "environmentId": environment_id,
    }
    if deployment_id:
        variables["deploymentId"] = deployment_id
    query = """
    query GetRuntimeLogs(
      $serviceId: ObjectID!
      $projectId: ObjectID!
      $environmentId: ObjectID!
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
    data = await gql(query, variables)
    if "error" in data:
        return f"❌ {data['error']}"
    logs = extract_logs(data)
    if not logs.strip() or logs.strip() == "{}":
        return "📭 没有运行时日志"
    return f"📋 运行时日志 ({service_id[:12]}...):\n\n{logs}"


@mcp.tool()
async def get_regions() -> str:
    """列出 Zeabur 可用的区域和服务器"""
    query = """
    query ListRegions {
      servers {
        edges {
          node {
            _id
            displayName
            regionCode
            available
            price
          }
        }
      }
    }
    """
    data = await gql(query)
    if "error" in data:
        return f"❌ {data['error']}"
    servers = data.get("servers", {}).get("edges", [])
    if not servers:
        return "📭 没有可用区域"
    lines = []
    for s in servers:
        n = s["node"]
        avail = "✅" if n.get("available") else "❌"
        lines.append(f"{avail} {n['displayName']} ({n['regionCode']}) - server-{n['_id']} ${n.get('price', '?')}")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# FastAPI + SSE/Streamable HTTP 双模式
# ═══════════════════════════════════════════

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Zeabur MCP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# SSE 模式
_sse_transport = SseServerTransport("/messages")

@app.get("/sse")
async def handle_sse(request: Request):
    async with _sse_transport.connect_sse(request) as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream, write_stream,
            mcp._mcp_server.create_initialization_options(),
        )


@app.post("/messages")
async def handle_messages(request: Request):
    await _sse_transport.handle_post_message(request)
    return Response()


# Streamable HTTP 模式
@app.post("/mcp")
async def handle_mcp(request: Request):
    body = await request.json()
    server = mcp._mcp_server

    class StreamResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {
                "content-type": "text/event-stream",
                "cache-control": "no-cache",
                "connection": "keep-alive",
            }
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
    ok = "✅" if ZEABUR_TOKEN else "❌ 未配置 ZEABUR_TOKEN"
    return JSONResponse({"status": "ok", "token": ok})


# ═══════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print(f"🔧 Zeabur MCP Server")
    print(f"   SSE:  http://localhost:{PORT}/sse")
    print(f"   HTTP: http://localhost:{PORT}/mcp")
    print(f"   Token: {'✅' if ZEABUR_TOKEN else '❌ 未配置'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, timeout_keep_alive=120)
