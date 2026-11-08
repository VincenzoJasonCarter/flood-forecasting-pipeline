-- TMA satu pos, @n langkah waktu terakhir: grafik halaman detail untuk rentang yang lebih
-- panjang dari history_steps (filter 1 minggu, 1 bulan, 1 tahun).
-- Placeholder: table = station_features, columns = kolom pos
-- Parameter  : @n INT64, jumlah langkah waktu (jam/hari) terakhir.
SELECT datetime, {columns}
FROM `{table}`
ORDER BY datetime DESC
LIMIT @n
