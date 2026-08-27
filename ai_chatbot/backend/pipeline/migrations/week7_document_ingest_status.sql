-- Week 7 -- make knowledge-base ingestion observable and restartable.
--
-- The spec calls for embeddings to be "generated and upserted via a background
-- job", and for a 100-page PDF to finish within 5 minutes. Upload used to
-- parse, chunk, embed and insert inline, so the HTTP request stayed open for
-- the whole job and the admin had no way to tell a slow ingest from a hung
-- one. The work now runs in the background, which only makes sense if its
-- progress is written down somewhere -- hence these columns.
--
-- ingest_status: pending -> running -> ready | failed
--
-- Idempotent: safe to re-run.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingest_status VARCHAR NOT NULL DEFAULT 'ready';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingest_error  TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_total   INTEGER;

-- Documents that predate this column finished ingesting long ago, so 'ready'
-- (the column default) is already correct for them. Backfill chunk_total from
-- what is actually in knowledge_chunks rather than guessing.
UPDATE documents d
   SET chunk_total = c.n
  FROM (SELECT document_id, COUNT(*) AS n FROM knowledge_chunks GROUP BY document_id) c
 WHERE c.document_id = d.id
   AND d.chunk_total IS NULL;

CREATE INDEX IF NOT EXISTS documents_ingest_status_idx ON documents (ingest_status);
