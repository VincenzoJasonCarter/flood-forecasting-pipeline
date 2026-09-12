"""Production entrypoint.

Alias tipis untuk src/predict.py — satu-satunya job yang perlu dijalankan
berulang di produksi (preprocessing sudah dilakukan sekali dan bobot model
tidak perlu retraining, lihat src/preprocessing dan src/load_best_model.py
untuk keperluan setup/debug).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from predict import main  # noqa: E402

if __name__ == "__main__":
    main()
