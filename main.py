from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
import httpx
import os
import json

# ═══════════════════════════════════════════
# 🦊 Zeabur MCP
# ═══════════════════════════════════════════

ZEABUR_TOKEN = os.environ.get("ZEABUR_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8765))
GRAPHQL_URL = "https://api.zeabur.com/graphql"

mcp = FastMCP("Zeabur")


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
            _id name
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
async def create_project(name: str) -> str:
    """创建一个新的 Zeabur 项目。"""
    query = """
    mutation CreateProject($name: String!, $regionCode: String) {
      createProject(name: $name, regionCode: $regionCode) { _id name }
    }
    """
    data = await gql(query, {"name": name})
    if "error" in data:
        return f"❌ 创建项目失败: {data['error']}"
    p = data.get("createProject", {})
    if not p:
        return "❌ 创建项目失败"
    return f"✅ 项目创建成功！\n   名称: {p['name']} | ID: {p['_id']}"


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
    for d in svc.get("domains", []):
        lines.append(f"   🌐 {d['domain']} ({d['status']})")
    deploys = svc.get("deployments", [])
    if deploys:
        d = deploys[0]
        lines.append(f"   📋 最近部署: {d['status']} @ {d.get('createdAt','N/A')[:19]}")
        lines.append(f"      部署ID: {d['_id']}")
    return "\n".join(lines)


@mcp.tool()
async def create_service(name: str, project_id: str) -> str:
    """在指定项目中创建一个新的 PREBUILT 服务。创建后需用 bind_git_repo 绑定 GitHub 仓库。"""
    query = """
    mutation CreateService($name: String!, $projectID: ObjectID!) {
      createService(name: $name, template: PREBUILT_V2, projectID: $projectID) {
        _id name status
      }
    }
    """
    data = await gql(query, {"name": name, "projectID": project_id})
    if "error" in data:
        return f"❌ 创建服务失败: {data['error']}"
    svc = data.get("createService", {})
    if not svc:
        return "❌ 创建服务失败"
    return f"✅ 服务创建成功！\n   名称: {svc['name']} | ID: {svc['_id']}\n   ⚠️ 下一步: 用 bind_git_repo 绑定 GitHub 仓库"


@mcp.tool()
async def bind_git_repo(service_id: str, repo_url: str, branch: str = "main") -> str:
    """将 GitHub 仓库绑定到指定服务。绑定后会自动触发部署。"""
    query = """
    mutation BindGitRepo($serviceID: ObjectID!, $url: String!, $branch: String!) {
      bindGitRepository(serviceID: $serviceID, url: $url, branch: $branch) {
        _id name status
      }
    }
    """
    data = await gql(query, {
        "serviceID": service_id,
        "url": repo_url,
        "branch": branch,
    })
    if "error" in data:
        return f"❌ 绑定仓库失败: {data['error']}"
    svc = data.get("bindGitRepository", {})
    if not svc:
        return "❌ 绑定仓库失败"
    return f"✅ 仓库绑定成功！\n   服务: {svc['name']} | ID: {svc['_id']}\n   📋 已自动触发部署"


@mcp.tool()
async def set_env_var(service_id: str, environment_id: str, key: str, value: str) -> str:
    """为指定服务设置环境变量。"""
    query = """
    mutation CreateEnvVar($serviceID: ObjectID!, $environmentID: ObjectID!, $key: String!, $value: String!) {
      createEnvironmentVariable(serviceID: $serviceID, environmentID: $environmentID, key: $key, value: $value) {
        key value
      }
    }
    """
    data = await gql(query, {
        "serviceID": service_id,
        "environmentID": environment_id,
        "key": key,
        "value": value,
    })
    if "error" in data:
        return f"❌ 设置环境变量失败: {data['error']}"
    v = data.get("createEnvironmentVariable", {})
    if not v:
        return "❌ 设置失败"
    return f"✅ {v['key']} = {v['value']}"


@mcp.tool()
async def get_env_vars(service_id: str, environment_id: str) -> str:
    """获取指定服务的所有环境变量。"""
    query = """
    query ServiceVars($serviceID: ObjectID!, $environmentID: ObjectID!) {
      service(_id: $serviceID) {
        variables(environmentID: $environmentID) { key value }
      }
    }
    """
    data = await gql(query, {
        "serviceID": service_id,
        "environmentID": environment_id,
    })
    if "error" in data:
        return f"❌ {data['error']}"
    svc = data.get("service", {})
    vars_ = svc.get("variables", []) if svc else []
    if not vars_:
        return "📭 没有环境变量"
    lines = [f"📋 环境变量:"]
    for v in vars_:
        lines.append(f"   {v['key']} = {v['value']}")
    return "\n".join(lines)


@mcp.tool()
async def delete_env_var(service_id: str, environment_id: str, key: str) -> str:
    """删除指定服务的某个环境变量。"""
    query = """
    mutation DeleteEnvVar($serviceID: ObjectID!, $environmentID: ObjectID!, $key: String!) {
      deleteSingleEnvironmentVariable(serviceID: $serviceID, environmentID: $environmentID, key: $key) {
        key
      }
    }
    """
    data = await gql(query, {
        "serviceID": service_id,
        "environmentID": environment_id,
        "key": key,
    })
    if "error" in data:
        return f"❌ 删除失败: {data['error']}"
    return f"✅ 环境变量 {key} 已删除"


@mcp.tool()
async def get_deployments(service_id: str, environment_id: str) -> str:
    """获取服务的部署历史。"""
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
        lines.append(f"   状态: {n['status']} | 创建: {n.get('createdAt','N/A')[:19]}")
    return "\n".join(lines)


@mcp.tool()
async def get_build_logs(deployment_id: str) -> str:
    """获取指定部署的构建日志。"""
    query = """
    query BuildLogs($deploymentId: ObjectID!) {
      buildLogs(deploymentID: $deploymentId) { message timestamp }
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
        lines.append(f"  [{entry.get('timestamp','')[:19]}] {entry.get('message','')}")
    if len(logs) > 200:
        lines.append(f"  ... 共 {len(logs)} 条")
    return "\n".join(lines)


@mcp.tool()
async def get_runtime_logs(service_id: str, environment_id: str, project_id: str, deployment_id: str = "") -> str:
    """获取服务运行时日志。"""
    query = """
    query GetRuntimeLogs($serviceId: ObjectID!, $environmentId: ObjectID!, $projectId: ObjectID!, $deploymentId: ObjectID) {
      runtimeLogs(serviceID: $serviceId, environmentID: $environmentId, projectID: $projectId, deploymentID: $deploymentId) {
        message timestamp
      }
    }
    """
    variables = {"serviceId": service_id, "environmentId": environment_id, "projectId": project_id}
    if deployment_id:
        variables["deploymentId"] = deployment_id
    data = await gql(query, variables)
    if "error" in data:
        return f"❌ {data['error']}"
    logs = data.get("runtimeLogs", [])
    if not logs:
        return "📭 没有运行时日志"
    lines = [f"📋 运行时日志:"]
    for entry in logs[-200:]:
        lines.append(f"  [{entry.get('timestamp','')[:19]}] {entry.get('message','')}")
    if len(logs) > 200:
        lines.append(f"  ... 共 {len(logs)} 条")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# FastAPI + SSE (手动挂载，避免307重定向)
# ═══════════════════════════════════════════

app = FastAPI(title="Zeabur MCP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "token_set": bool(ZEABUR_TOKEN)})


@app.get("/sse")
@app.post("/sse")
async def sse_endpoint(request: Request):
    """SSE 端点 - 不用 mount 避免 307 重定向"""
    from starlette.responses import StreamingResponse
    from mcp.server.sse import SseServerTransport

    sse = SseServerTransport("/messages")
    async def stream():
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            read_stream, write_stream = streams
            await mcp._mcp_server.run(read_stream, write_stream, mcp._mcp_server.create_initialization_options())
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/messages")
async def messages_endpoint(request: Request):
    """SSE 消息回调端点"""
    from mcp.server.sse import SseServerTransport
    sse = SseServerTransport("/messages")
    return await sse.handle_post_message(request)


if __name__ == "__main__":
    import uvicorn
    print(f"🦊 Zeabur MCP Server")
    print(f"   SSE:   http://localhost:{PORT}/sse")
    print(f"   Token: {'✅' if ZEABUR_TOKEN else '❌'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, timeout_keep_alive=120)
