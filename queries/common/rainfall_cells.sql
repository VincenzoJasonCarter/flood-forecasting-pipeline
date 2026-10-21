-- Kolom sel hujan terpilih dari tabel hujan (rainfall_hourly).
-- Placeholder: table = project.dataset.table, columns = daftar kolom rain_<lat>_<lon>
-- Parameter  : @since DATETIME, boleh NULL (NULL = seluruh histori; training).
--              Serving mengisinya supaya hanya jam >= @since yang dibaca.
SELECT datetime, {columns}
FROM `{table}`
WHERE @since IS NULL OR datetime >= @since
ORDER BY datetime
