import pytest
from sklearn.preprocessing import MinMaxScaler

from prediction.scalers import inverse_transform


def test_inverse_transform_maps_back_to_original_scale():
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaler.fit([[0.0], [50.0], [100.0]])

    assert inverse_transform(scaler, 0.0) == pytest.approx(0.0)
    assert inverse_transform(scaler, 1.0) == pytest.approx(100.0)
    assert inverse_transform(scaler, 0.5) == pytest.approx(50.0)
