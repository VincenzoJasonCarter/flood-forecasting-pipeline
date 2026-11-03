-- @n baris terakhir tabel wide ber-index datetime: station_features (TMA per stasiun)
-- atau rainfall (hujan per sel grid).
-- Placeholder: table = tabel sumber
-- Parameter  : @n INT64, jumlah langkah waktu (jam/hari) terakhir.
SELECT *
FROM `{table}`
ORDER BY datetime DESC
LIMIT @n
