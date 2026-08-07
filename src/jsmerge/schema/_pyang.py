"""pyang integration for schema builds (imported lazily; pyang is slow to import)."""

from __future__ import annotations

import importlib
from types import ModuleType

_PYANG_IMPORT_ERROR = "pyang is required for schema build; pip install pyang"


def load_pyang() -> tuple[ModuleType, ModuleType]:
    """Import pyang modules on first use."""
    try:
        context = importlib.import_module("pyang.context")
        repository = importlib.import_module("pyang.repository")
    except ModuleNotFoundError as exc:
        raise RuntimeError(_PYANG_IMPORT_ERROR) from exc
    return context, repository
