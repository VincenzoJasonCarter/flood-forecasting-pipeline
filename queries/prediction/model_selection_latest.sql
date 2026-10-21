-- Hasil pemilihan model terbaik yang paling baru disimpan (05_Model_Selection).
-- Placeholder: table = tabel model_selection
SELECT best_model, selection_metric, mean_value
FROM `{table}`
ORDER BY saved_at DESC
LIMIT 1
