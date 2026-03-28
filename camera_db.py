# camera_db.py
CAMERA_DB = {
    "EOS 5D Mark II": 150000,
    "EOS 5D Mark III": 150000,
    "EOS 5D Mark IV": 150000,
    "EOS 6D": 100000,
    "EOS 6D Mark II": 100000,
    "EOS 7D": 150000,
    "EOS 7D Mark II": 200000,
    "EOS 60D": 100000,
    "EOS 70D": 100000,
    "EOS 80D": 100000,
}


def normalize_model_name(name):
    """Strip 'Canon ' prefix and whitespace. gphoto2 reports 'Canon EOS 5D Mark II', DB keys use 'EOS 5D Mark II'."""
    name = name.strip()
    if name.startswith("Canon "):
        name = name[6:]
    return name


def get_rated_lifespan(model_name):
    """Return rated shutter lifespan for a model, or None if unknown."""
    normalized = normalize_model_name(model_name)
    return CAMERA_DB.get(normalized)
