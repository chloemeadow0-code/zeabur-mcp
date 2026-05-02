from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
import httpx
import os
import json

# ═══════════════════════════════════════════
# 🦊 Zeabur MCP - HTTP/SSE 双模式
# ═══════════════════════════════════════════
#
# 部署到 Zeabur，RikkaHub 添加 MCP 连接:
#   SSE:      https://你的域名/sse
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
# MCP 工具 - 项目
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
async def create_project(name: str) -> str:
    """创建一个新的 Zeabur 项目。"""
    query = """
    mutation CreateProject($name: String!, $regionCode: String) {
      createProject(name: $name, regionCode: $regionCode) {
        _id
        name
      }
    }
    """
    data = await gql(query, {"name": name})
    if "error" in data:
        return f"❌ 创建项目失败: {data['error']}"
    project = data.get("createProject", {})
    if not project:
        return "❌ 创建项目失败，未知错误"
    return f"✅ 项目创建成功！\n   名称: {project['name']}\n   ID: {project['_id']}\n   用 list_projects 查看完整信息"


# ═══════════════════════════════════════════
# MCP 工具 - 服务
# ═══════════════════════════════════════════

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
async def create_service(name: str, project_id: str) -> str:
    """在指定项目中创建一个新的 PREBUILT 服务。创建后需用 bind_git_repo 绑定 GitHub 仓库。"""
    query = """
    mutation CreateService($name: String!, $projectID: ObjectID!) {
      createService(name: $name, template: PREBUILT_V2, projectID: $projectID) {
        _id
        name
        status
      }
    }
    """
    data = await gql(query, {"name": name, "projectID": project_id})
    if "error" in data:
        return f"❌ 创建服务失败: {data['error']}"
    svc = data.get("createService", {})
    if not svc:
        return "❌ 创建服务失败，未知错误"
    return f"✅ 服务创建成功！\n   名称: {svc['name']}\n   ID: {svc['_id']}\n   状态: {svc.get('status', 'N/A')}\n   ⚠️ 下一步: 用 bind_git_repo 绑定 GitHub 仓库"


@mcp.tool()
async def bind_git_repo(service_id: str, repo_url: str, branch: str = "main") -> str:
    """将 GitHub 仓库绑定到指定服务。绑定后会自动触发部署。"""
    query = """
    mutation BindGitRepo($serviceID: ObjectID!, $url: String!, $branch: String!) {
      bindGitRepository(serviceID: $serviceID, url: $url, branch: $branch) {
        _id
        name
        status
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
        return "❌ 绑定仓库失败，未知错误"
    return f"✅ 仓库绑定成功！\n   服务: {svc['name']} (ID: {svc['_id']})\n   状态: {svc.get('status', 'N/A')}\n   📋 已自动触发部署，用 get_deployments 查看进度"


@mcp.tool()
async def set_env_var(service_id: str, environment_id: str, key: str, value: str) -> str:
    """为指定服务设置环境变量。"""
    query = """
    mutation CreateEnvVar($serviceID: ObjectID!, $environmentID: ObjectID!, $key: String!, $value: String!) {
      createEnvironmentVariable(serviceID: $serviceID, environmentID: $environmentID, key: $key, value: $value) {
        key
        value
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
    var_ = data.get("createEnvironmentVariable", {})
    if not var_:
        return "❌ 设置环境变量失败，未知错误"
    return f"✅ 环境变量设置成功！\n   {var_['key']} = {var_['value']}"


@mcp.tool()
async def get_env_vars(service_id: str, environment_id: str) -> str:
    """获取指定服务的所有环境变量。"""
    query = """
    query ServiceVars($serviceID: ObjectID!, $environmentID: ObjectID!) {
      service(_id: $serviceID) {
        variables(environmentID: $environmentID) {
          key
          value
        }
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
    lines = [f"📋 环境变量 (服务: {service_id}):"]
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
        return f"❌ 删除环境变量失败: {data['error']}"
    return f"✅ 环境变量 {key} 已删除"


# ═══════════════════════════════════════════
# MCP 工具 - 部署与日志
# ═══════════════════════════════════════════

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
# FastAPI + SSE
# ═══════════════════════════════════════════

app = FastAPI(title="Zeabur MCP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    status = "ok" if ZEABUR_TOKEN else "missing_token"
    return JSONResponse({"status": status, "token_set": bool(ZEABUR_TOKEN)})

app.mount("/sse", mcp.sse_app())
app.mount("/mcp", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn
    print(f"🦊 Zeabur MCP Server")
    print(f"   SSE:   http://localhost:{PORT}/sse")
    print(f"   HTTP:  http://localhost:{PORT}/mcp")
    print(f"   Token: {'✅ 已设置' if ZEABUR_TOKEN else '❌ 未设置'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
