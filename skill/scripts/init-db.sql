-- SummerMemory 数据库初始化
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 记忆表
CREATE TABLE IF NOT EXISTS memories (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    content TEXT,
    embedding vector(384),
    content_tsv tsvector,
    metadata JSONB DEFAULT '{}',
    hash TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 活动记录表
CREATE TABLE IF NOT EXISTS memory_activity (
    id SERIAL PRIMARY KEY,
    action TEXT,
    path TEXT,
    query TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_memories_path ON memories(path);
CREATE INDEX IF NOT EXISTS idx_memories_tsv ON memories USING GIN(content_tsv);
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON memory_activity(timestamp DESC);

-- 唯一约束（防止重复）
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_path_unique ON memories(path);
