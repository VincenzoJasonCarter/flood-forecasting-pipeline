-- Bobot LSTM/GRU/TFT per (stasiun, horizon).
-- Placeholder: table = tabel bobot model (mis. lstm_weights_hourly)
-- Parameter  : @station STRING dan @horizon INT64, masing-masing boleh NULL (NULL = tanpa filter)
SELECT station, horizon, weights
FROM `{table}`
WHERE (@station IS NULL OR station = @station)
  AND (@horizon IS NULL OR horizon = @horizon)
