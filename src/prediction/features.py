"""Which feature columns each model expects, read from preprocessing_metadata."""

# Varian ablation tanpa fitur hujan (USE_RAINFALL=False di notebook 01-04)
# disimpan sebagai mis. "lstm_norain"; arsitekturnya tetap "lstm".
NORAIN_SUFFIX = "_norain"


def split_model_name(model_name):
    """'lstm_norain' -> ('lstm', False); 'lstm' -> ('lstm', True)."""
    if model_name.endswith(NORAIN_SUFFIX):
        return model_name[:-len(NORAIN_SUFFIX)], False
    return model_name, True


def feature_cols_for(metadata, station, use_rain=True):
    """Urutan kolom input model untuk stasiun target, sama dengan saat training.

    Metadata lama (sebelum ada fitur hujan/kalender sin-cos) hanya punya
    `feature_cols`, yang dipakai semua stasiun."""
    by_station = metadata.get("feature_cols_by_station")
    if use_rain and by_station:
        return by_station[station]
    return metadata.get("base_feature_cols", metadata["feature_cols"])


def required_history(metadata, lookback):
    """Jumlah baris terakhir yang perlu dibaca: jendela model + jendela
    akumulasi hujan terpanjang (supaya baris pertama jendela sudah lengkap)."""
    accum = metadata.get("rain_accum_hours") or [1]
    return lookback + max(accum) - 1
