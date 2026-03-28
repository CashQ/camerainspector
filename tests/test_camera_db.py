from camera_db import get_rated_lifespan, normalize_model_name


def test_normalize_strips_canon_prefix():
    assert normalize_model_name("Canon EOS 5D Mark II") == "EOS 5D Mark II"


def test_normalize_preserves_eos_prefix():
    assert normalize_model_name("EOS 5D Mark II") == "EOS 5D Mark II"


def test_normalize_strips_whitespace():
    assert normalize_model_name("  Canon EOS 6D  ") == "EOS 6D"


def test_known_model_returns_lifespan():
    assert get_rated_lifespan("Canon EOS 5D Mark II") == 150000


def test_known_model_without_prefix():
    assert get_rated_lifespan("EOS 7D Mark II") == 200000


def test_unknown_model_returns_none():
    assert get_rated_lifespan("Canon EOS R5") is None


def test_all_models_have_positive_lifespan():
    from camera_db import CAMERA_DB
    for model, lifespan in CAMERA_DB.items():
        assert lifespan > 0, f"{model} has invalid lifespan {lifespan}"
