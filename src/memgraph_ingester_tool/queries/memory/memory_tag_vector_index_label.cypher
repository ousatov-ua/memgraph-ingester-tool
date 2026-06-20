MATCH (chunk:MemoryChunk {project: $project})
WHERE chunk.id IN $ids
SET chunk:__VECTOR_INDEX_LABEL__
RETURN count(chunk) AS count
