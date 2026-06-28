"""Optional pyang integration for schema builds."""

from __future__ import annotations

import importlib
from types import ModuleType

_PYANG_IMPORT_ERROR = "pyang is required for schema build; pip install jsmerge[build-schema]"


def load_pyang() -> tuple[ModuleType, ModuleType]:
    """Import pyang modules when the build-schema extra is installed."""
    try:
        context = importlib.import_module("pyang.context")
        repository = importlib.import_module("pyang.repository")
    except ModuleNotFoundError as exc:
        raise RuntimeError(_PYANG_IMPORT_ERROR) from exc
    return context, repository
