-- Week 7 -- tenant-scope the knowledge base.
--
-- NFR: "RAG retrieval must not surface another student's personal data in any
-- response -- retrieval is scoped by tenant". Retrieval was reading every row
-- in knowledge_chunks regardless of who asked, because neither `documents` nor
-- `knowledge_chunks` carried a tenant_id at all. A single-tenant dataset hid
-- the gap; a second tenant would have leaked immediately.
--
-- tenant_id is denormalised onto knowledge_chunks rather than reached through
-- documents on every query: the retrieval path is an ANN scan over 3072-dim
-- vectors, and making it join before it can filter is the one thing that
-- reliably makes pgvector slow.
--
-- Backfill is 'uet' because that is the only tenant present in students,
-- exams, user_info and conversations at the time of writing.
--
-- Idempotent: safe to re-run.

ALTER TABLE documents        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS tenant_id VARCHAR;

UPDATE documents        SET tenant_id = 'uet' WHERE tenant_id IS NULL;
UPDATE knowledge_chunks SET tenant_id = 'uet' WHERE tenant_id IS NULL;

-- Existing chunks inherit whatever their parent document says, so a document
-- moved between tenants later stays consistent with its chunks.
UPDATE knowledge_chunks k
   SET tenant_id = d.tenant_id
  FROM documents d
 WHERE d.id = k.document_id
   AND d.tenant_id IS NOT NULL
   AND k.tenant_id IS DISTINCT FROM d.tenant_id;

ALTER TABLE documents        ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE documents        ALTER COLUMN tenant_id SET DEFAULT 'uet';
ALTER TABLE knowledge_chunks ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE knowledge_chunks ALTER COLUMN tenant_id SET DEFAULT 'uet';

-- Retrieval filters on tenant_id before ordering by distance, and exam-mode
-- retrieval additionally filters on documents.document_type.
CREATE INDEX IF NOT EXISTS knowledge_chunks_tenant_idx
    ON knowledge_chunks (tenant_id);
CREATE INDEX IF NOT EXISTS documents_tenant_type_idx
    ON documents (tenant_id, document_type);
