-- Metadata preprocessing (payload JSON) yang paling baru disimpan.
-- Placeholder: table = tabel preprocessing_metadata
SELECT payload
FROM `{table}`
ORDER BY saved_at DESC
LIMIT 1
