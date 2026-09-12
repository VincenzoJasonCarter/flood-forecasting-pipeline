"""End-to-end forecasting pipeline.

Memuat model terbaik (`model_selection`), menjalankannya terhadap data
`station_features` paling baru, dan mengembalikan hasil forecast yang sudah
di-inverse-scale kembali ke satuan asli (cm) — tanpa perlu training ulang,
notebook, atau disk lokal.

Pemakaian:
    from prediction import forecast_latest
    forecast_df, model_name = forecast_latest()
"""

from .best_model import load_best_model
from .pipeline import forecast_latest

__all__ = ["forecast_latest", "load_best_model"]
