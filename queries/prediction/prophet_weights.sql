-- Model Prophet per stasiun.
-- Placeholder: table = tabel bobot model (mis. lstm_weights_hourly)
-- Parameter  : @station STRING, boleh NULL (NULL = semua stasiun)
SELECT station, weights
FROM `{table}`
WHERE @station IS NULL OR station = @station
