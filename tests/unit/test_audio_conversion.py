from __future__ import annotations

import numpy as np
import pytest

from whisperlite.transcribe import _int16_to_float32


def test_all_zeros_int16_becomes_all_zeros_float32() -> None:
    arr = np.zeros(100, dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.dtype == np.float32
    assert np.all(out == 0.0)


def test_max_int16_maps_to_approximately_one() -> None:
    arr = np.array([32767], dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.dtype == np.float32
    assert abs(out[0] - (32767.0 / 32768.0)) < 1e-6
    assert out[0] < 1.0


def test_min_int16_maps_to_exactly_minus_one() -> None:
    arr = np.array([-32768], dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.dtype == np.float32
    assert out[0] == -1.0


def test_output_dtype_is_float32() -> None:
    arr = np.array([1, 2, 3, -4], dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.dtype == np.float32


def test_output_shape_matches_input_shape_1d() -> None:
    arr = np.zeros(512, dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.shape == arr.shape


def test_output_shape_matches_input_shape_2d() -> None:
    arr = np.zeros((128, 2), dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.shape == arr.shape
    assert out.dtype == np.float32


def test_wrong_dtype_raises_type_error() -> None:
    arr = np.zeros(10, dtype=np.float32)
    with pytest.raises(TypeError):
        _int16_to_float32(arr)


def test_non_ndarray_raises_type_error() -> None:
    with pytest.raises(TypeError):
        _int16_to_float32([1, 2, 3])  # type: ignore[arg-type]


def test_values_are_in_unit_range() -> None:
    arr = np.array([-32768, -16384, 0, 16384, 32767], dtype=np.int16)
    out = _int16_to_float32(arr)
    assert out.min() >= -1.0
    assert out.max() <= 1.0
