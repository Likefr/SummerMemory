-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 创建记忆表
CREATE TABLE IF NOT EXISTS memories (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(512),
    content_tsv TSVECTOR,
    metadata JSONB DEFAULT '{}',
    hash TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 创建向量索引（IVFFlat，适用于中小规模数据）
CREATE INDEX IF NOT EXISTS memories_embedding_idx
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 2);

-- 创建路径索引
CREATE INDEX IF NOT EXISTS memories_path_idx ON memories (path);

-- 创建哈希索引（用于变更检测）
CREATE INDEX IF NOT EXISTS memories_hash_idx ON memories (hash);

-- 创建活动日志表
CREATE TABLE IF NOT EXISTS memory_activity (
    id SERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    path TEXT,
    query TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);
