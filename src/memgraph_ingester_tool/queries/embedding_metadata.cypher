MATCH (chunk {project: $project})
WHERE (chunk:CodeChunk OR chunk:MemoryChunk)
  AND chunk.embedding IS NOT NULL
  AND chunk.embeddingModel IS NOT NULL
  AND chunk.embeddingModel <> ''
WITH chunk,
     CASE WHEN $preferred_label IN labels(chunk) THEN 0 ELSE 1 END AS priority
RETURN chunk.embeddingModel AS modelName,
       chunk.embeddingDimensions AS dimensions,
       priority,
       count(chunk) AS count
ORDER BY priority ASC, count DESC, modelName ASC
LIMIT 1
