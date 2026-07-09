"""Rejestr motywów nakładki simple-tts.

get_theme(name, w, h, scale) zwraca instancję motywu; nieznana nazwa spada
na KITT (bezpieczny default — nakładka nigdy nie umiera przez literówkę
w configu). Nazwy motywów: klucz `overlay_theme` w simple-tts-config.json.
"""

from .kitt import CylonTheme, KittTheme
from .spark import SparkTheme

_REGISTRY = {
    "kitt": KittTheme,
    "cylon": CylonTheme,
    "spark": SparkTheme,
}

THEME_NAMES = tuple(sorted(_REGISTRY))


def get_theme(name, w, h, scale):
    cls = _REGISTRY.get(str(name).strip().lower(), KittTheme)
    return cls(w, h, scale)
