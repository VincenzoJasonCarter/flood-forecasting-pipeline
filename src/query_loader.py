"""Load the SQL files in queries/ and fill in table / column identifiers.

Semua SQL BigQuery ada sebagai file .sql di queries/, bukan string di kode
Python. Nilai (stasiun, horizon, batas waktu) dikirim sebagai query parameter
(@name); hanya nama tabel dan kolom, yang tidak bisa jadi parameter, diisi ke
placeholder `{table}` / `{columns}` setelah divalidasi di sini.

File .sql tidak boleh berisi kurung kurawal selain placeholder tsb. (termasuk
di komentar), karena diisi dengan str.format.
"""

import re
from functools import lru_cache

from settings import CONFIG_DIR

QUERIES_DIR = CONFIG_DIR.parent / "queries"

# project.dataset.table: huruf/angka/underscore/strip (project id boleh ber-strip).
_TABLE_ID = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){0,2}")
_FORBIDDEN_IN_COLUMN = "`\\\r\n"


@lru_cache(maxsize=None)
def read_query(name):
    """Isi mentah queries/{name}.sql (mis. name="prediction/scalers")."""
    path = QUERIES_DIR / f"{name}.sql"
    if not path.is_file():
        raise FileNotFoundError(f"Query '{name}' tidak ditemukan: {path}")
    return path.read_text(encoding="utf-8")


def quote_columns(columns):
    """`a`, `b`, ... untuk daftar nama kolom; menolak nama yang bisa keluar dari backtick."""
    columns = list(columns)
    if not columns:
        raise ValueError("Daftar kolom kosong.")
    for column in columns:
        if not column or any(ch in column for ch in _FORBIDDEN_IN_COLUMN):
            raise ValueError(f"Nama kolom tidak valid: {column!r}")
    return ", ".join(f"`{column}`" for column in columns)


def load_query(name, *, table, columns=None):
    """SQL siap jalan untuk queries/{name}.sql dengan `table` (dan `columns`) terisi."""
    if not _TABLE_ID.fullmatch(table):
        raise ValueError(f"Nama tabel tidak valid: {table!r}")
    fields = {"table": table}
    if columns is not None:
        fields["columns"] = quote_columns(columns)
    return read_query(name).format(**fields)
