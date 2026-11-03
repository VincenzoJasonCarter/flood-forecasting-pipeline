-- Hasil pemilihan model terbaik yang paling baru disimpan (05_Model_Selection).
-- SELECT * karena skema statistiknya berubah: tabel lama punya mean_value, yang baru median_value;
-- pemanggil memakai kolom yang ada (prediction/best_model.py dan dashboard/data.py).
-- Placeholder: table = tabel model_selection
SELECT *
FROM `{table}`
ORDER BY saved_at DESC
LIMIT 1
