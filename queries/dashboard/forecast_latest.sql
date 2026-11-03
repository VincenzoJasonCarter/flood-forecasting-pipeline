-- Forecast run terbaru dari log forecast_output (WRITE_APPEND): hanya baris dengan as_of terakhir,
-- supaya papan dan grafik tidak mencampur horizon/stasiun dari run lama dengan "sekarang" yang
-- berbeda. Dalam as_of itu, baris terbaru per (stasiun, horizon): run ulang dengan --station /
-- --horizon pada as_of yang sama menimpa barisnya saja, baris lain tetap tampil.
-- Subquery MAX(as_of) hanya memindai kolom as_of; window function hanya jalan di satu run.
-- Placeholder: table = tabel forecast_output
SELECT model, station, horizon, as_of, forecast_time, predicted_value_cm, generated_at
FROM `{table}`
WHERE as_of = (SELECT MAX(as_of) FROM `{table}`)
QUALIFY generated_at = MAX(generated_at) OVER (PARTITION BY station, horizon)
ORDER BY station, horizon
