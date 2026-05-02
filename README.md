# Zeabur MCP Server

通过 RikkaHub 管理 Zeabur 云服务的 MCP 工具。

## 工具列表

| 工具 | 说明 |
|------|------|
| `list_projects` | 列出所有项目 |
| `list_services` | 列出项目下的服务 |
| `get_service` | 查看服务详情（域名、状态） |
| `get_deployments` | 查看部署记录 |
| `get_build_logs` | 查看构建日志 ⭐ |
| `get_runtime_logs` | 查看运行时日志 ⭐ |
| `get_regions` | 列出可用区域 |

## 部署到 Zeabur

1. 推送代码到 GitHub
2. 在 Zeabur 创建服务，关联本仓库
3. 设置环境变量: `ZEABUR_TOKEN` = 你的 Zeabur API Token
4. 启动命令: `python main.py`

## RikkaHub 连接

- Streamable HTTP: `https://你的域名/mcp`
- SSE: `https://你的域名/sse`
