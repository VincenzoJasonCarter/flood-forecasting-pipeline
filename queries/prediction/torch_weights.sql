-- Bobot LSTM/GRU/TFT: per (stasiun, horizon) untuk model direct, atau satu
-- baris per stasiun dengan horizon NULL untuk model MIMO (semua horizon).
-- Placeholder: table = tabel bobot model (mis. lstm_weights_hourly)
-- Parameter  : @station STRING dan @horizon INT64, masing-masing boleh NULL (NULL = tanpa filter).
--              Baris MIMO selalu ikut; horizon-nya dipilih di Python.
SELECT station, horizon, weights
FROM `{table}`
WHERE (@station IS NULL OR station = @station)
  AND (@horizon IS NULL OR horizon IS NULL OR horizon = @horizon)
