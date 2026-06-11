# SummerMemory Graph 部署流程

**时间**：2026-06-11
**重要性**：每次改前端代码后的标准部署流程

## 部署命令
```bash
cd /root/.openclaw/workspace/memory-graph-vue
rm -rf dist node_modules/.vite
npm run build
python3 /tmp/deploy_graph.py
```

## 关键信息
- **公网地址**：https://ai.likefr.com/graph/
- **公网服务器**：47.119.123.204（root / POIASD520--=）
- **静态文件路径**：/www/wwwroot/ai.likefr.com/graph/
- **本地代码**：/root/.openclaw/workspace/memory-graph-vue/
- **deploy 脚本**：/tmp/deploy_graph.py（paramiko SCP 上传）

## 固定端口（不许改！）
- HTTP API：11435（FRP 穿透）
- WebSocket：8890（FRP 穿透）
- PostgreSQL：5432
- Ollama：11434

## 注意
- 本地 docker nginx 的 html 目录**不是** Graph 的部署目标
- 必须上传到公网服务器
- 代码在 GitLab + GitHub，端口路径是固定约定
