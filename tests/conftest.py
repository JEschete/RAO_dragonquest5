from __future__ import annotations

from collections.abc import Iterator
import importlib
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")


@pytest.fixture(scope="session")
def plugin_package() -> Iterator[str]:
    name = "_dq5_plugin_tests"
    assert name not in sys.modules
    package = ModuleType(name)
    package.__package__ = name
    setattr(package, "__path__", [str(Path(__file__).resolve().parents[1])])
    sys.modules[name] = package
    yield name
    for module_name in tuple(sys.modules):
        if module_name == name or module_name.startswith(name + "."):
            sys.modules.pop(module_name, None)


@pytest.fixture(scope="module", params=[
    "Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).bps",
    "Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F - Alt) (DeJap).bps",
], ids=["dejap", "dejap-alt"])
def owned_rom(request: pytest.FixtureRequest, plugin_package: str):
    directory = Path(__file__).resolve().parents[1] / "Resources/2148-DragonQuest5-English"
    source = directory / "Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    patch = directory / request.param
    if not source.is_file() or not patch.is_file():
        pytest.skip("Owned DQ5 ROM/patch inputs are not available")
    module = importlib.import_module(f"{plugin_package}.scripts.dq5_rom")
    return module.RomImage.load(source, patch)