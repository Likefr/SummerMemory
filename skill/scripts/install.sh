#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# SummerMemory 一键安装脚本
# Docker Compose 部署：PostgreSQL + pgvector + Ollama + SummerMemory
# ──────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 配置（可通过环境变量覆盖） ──
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
DB_NAME="${DB_NAME:-summermemory}"
DB_USER="${DB_USER:-summer}"
DB_PASSWORD="${DB_PASSWORD:-summer2026}"
DB_PORT="${DB_PORT:-5432}"
OLLAMA_MODEL="${OLLAMA_MODEL:-quentinz/bge-small-zh-v1.5}"
SERVER_PORT="${SERVER_PORT:-11435}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"

# ── 1. 检查依赖 ──
info "检查依赖..."

command -v docker >/dev/null 2>&1 || error "Docker 未安装，请先安装 Docker"
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || error "Docker Compose 未安装"

COMPOSE_CMD="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE_CMD="docker-compose"

info "使用 Compose 命令: $COMPOSE_CMD"

# ── 2. 创建 docker-compose.yml ──
info "创建 docker-compose.yml..."

mkdir -p "$PROJECT_DIR"

cat > "$PROJECT_DIR/docker-compose.yml" <<EOF
version: "3.8"

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: summermemory-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "${DB_PORT}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 5s
      timeout: 5s
      retries: 10

  ollama:
    image: ollama/ollama:latest
    container_name: summermemory-ollama
    restart: unless-stopped
    ports:
      - "${OLLAMA_PORT}:11434"
    volumes:
      - ollama_data:/root/.ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 10s
      timeout: 5s
      retries: 5

  summermemory:
    image: python:3.11-slim
    container_name: summermemory-server
    restart: unless-stopped
    working_dir: /app
    environment:
      DB_HOST: postgres
      DB_PORT: 5432
      DB_NAME: ${DB_NAME}
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      OLLAMA_HOST: http://ollama:11434
      OLLAMA_MODEL: ${OLLAMA_MODEL}
      MEMORY_DIR: /app/memory
      SERVER_PORT: ${SERVER_PORT}
    ports:
      - "${SERVER_PORT}:${SERVER_PORT}"
    volumes:
      - ./memory:/app/memory:ro
      - ./memory_system.py:/app/memory_system.py:ro
      - ./memory_server.py:/app/memory_server.py:ro
    depends_on:
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
    command: >
      bash -c "
        pip install --no-cache-dir psycopg2-binary requests jieba flask numpy &&
        python memory_server.py
      "
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:${SERVER_PORT}/version"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
  ollama_data:
EOF

# 复制 init-db.sql
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/init-db.sql" ]; then
    mkdir -p "$PROJECT_DIR/scripts"
    cp "$SCRIPT_DIR/init-db.sql" "$PROJECT_DIR/scripts/init-db.sql"
fi

# 创建 memory 目录
mkdir -p "$PROJECT_DIR/memory"

# ── 3. 启动服务 ──
info "启动 Docker Compose 服务..."
cd "$PROJECT_DIR"
$COMPOSE_CMD up -d

# ── 4. 等待数据库就绪 ──
info "等待 PostgreSQL 就绪..."
for i in $(seq 1 30); do
    if docker exec summermemory-db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

# ── 5. 拉取 Ollama 模型 ──
info "拉取 Ollama embedding 模型: ${OLLAMA_MODEL}..."
for i in $(seq 1 60); do
    if docker exec summermemory-ollama curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        docker exec summermemory-ollama ollama pull "$OLLAMA_MODEL"
        break
    fi
    sleep 3
done

# ── 6. 健康检查 ──
info "等待 SummerMemory 服务就绪..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${SERVER_PORT}/version" >/dev/null 2>&1; then
        info "✅ SummerMemory 服务已启动！"
        info "   API 地址: http://localhost:${SERVER_PORT}"
        info "   搜索示例: curl 'http://localhost:${SERVER_PORT}/search?q=测试&limit=5'"
        info "   统计信息: curl http://localhost:${SERVER_PORT}/stats"
        exit 0
    fi
    sleep 3
done

warn "服务启动超时，请检查日志："
warn "  $COMPOSE_CMD logs summermemory"
exit 1
