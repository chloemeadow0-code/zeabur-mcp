# 🦊 Zeabur MCP Server

HTTP/SSE 双模式的 Zeabur MCP 服务，部署到 Zeabur 后可通过 RikkaHub 连接。

## 功能

| 工具 | 说明 |
|------|------|
| `list_projects` | 列出所有项目 |
| `list_services` | 列出项目下的服务 |
| `get_service` | 获取服务详情（域名、部署等） |
| `get_deployments` | 查看部署历史 |
| `get_build_logs` | **查看构建日志** 🔥 |
| `get_runtime_logs` | **查看运行时日志** 🔥 |

## 部署

1. 推送到 GitHub
2. Zeabur 创建服务，连接仓库
3. 设置环境变量:
   - `ZEABUR_TOKEN` = 你的 Zeabur API Token
4. RikkaHub 添加 MCP 连接:
   - 类型: Streamable HTTP
   - 地址: `https://你的域名/mcp`

## 获取 API Token

Zeabur Dashboard → 设置 → API 密钥 → 生成
