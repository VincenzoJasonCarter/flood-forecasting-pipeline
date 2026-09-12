"""CLI: load the trained weights of whichever model `05_Model_Selection` picked as best.

Logika sesungguhnya ada di package `prediction` (`prediction.best_model`,
`prediction.architectures`); file ini cuma CLI tipis di atasnya.

Pemakaian:
    python load_best_model.py                     # load semua stasiun/horizon
    python load_best_model.py --station "Bendung Katulampa"
    python load_best_model.py --station "Bendung Katulampa" --horizon 3

Atau import langsung:
    from prediction import load_best_model
    models, model_name = load_best_model()
"""

import argparse

from prediction import load_best_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", default=None, help="Filter satu stasiun saja.")
    parser.add_argument("--horizon", type=int, default=None, help="Filter satu horizon saja (jam).")
    args = parser.parse_args()

    models, model_name = load_best_model(station=args.station, horizon=args.horizon)

    if model_name == "prophet":
        print(f"Loaded {len(models)} model Prophet: {sorted(models.keys())}")
    else:
        n_models = sum(len(h) for h in models.values())
        print(f"Loaded {n_models} model '{model_name}' ({len(models)} stasiun):")
        for st, horizons in models.items():
            print(f"  {st}: horizons={sorted(horizons.keys())}")


if __name__ == "__main__":
    main()
