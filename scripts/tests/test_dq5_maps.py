from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import dq5_maps
from dq5_map_data import MapHeader
from dq5_map_decode import DecodedFloor
from dq5_rom import RomImage


def test_decoder_uses_isolated_package_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    directory = Path(__file__).resolve().parents[1]
    name = "dq5_decoder_package_test"
    specification = importlib.util.spec_from_file_location(
        name, directory / "__init__.py", submodule_search_locations=[str(directory)],
    )
    assert specification is not None and specification.loader is not None
    package = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, name, package)
    specification.loader.exec_module(package)
    embedded = importlib.import_module(f"{name}.dq5_maps")
    assert embedded._hex_id("53") == 0x53
    assert embedded.RomImage.__module__ == f"{name}.dq5_rom"
    assert embedded.map_catalog.__module__ == f"{name}.dq5_map_data"
    assert embedded.decode_floor.__module__ == f"{name}.dq5_map_decode"


def test_export_directory_is_stable_and_rom_specific(tmp_path: Path) -> None:
    rom = RomImage(b"", "test", "a" * 32)
    options = {"selection": "all", "era": 1}
    destination = dq5_maps._export_directory(tmp_path, rom, options)
    assert destination == dq5_maps._export_directory(tmp_path, rom, dict(reversed(list(options.items()))))
    assert destination != dq5_maps._export_directory(tmp_path, RomImage(b"", "test", "b" * 32), options)
    assert destination.parent.name == f"v{dq5_maps.DECODER_VERSION}-{rom.md5}"


@pytest.mark.parametrize("key, value", [
    ("selection", "world-0"), ("era", 2), ("layer", "base"), ("scale", 2),
    ("world_region", [0, 0, 16, 16]), ("markers", False), ("ram_sha256", "different snapshot"),
])
def test_export_directory_separates_render_and_state_options(tmp_path: Path, key: str, value: object) -> None:
    rom = RomImage(b"", "test", "a" * 32)
    options = {"selection": "all", "era": 1, "layer": "combined", "scale": 1,
               "world_region": [0, 0, 512, 512], "markers": True, "ram_sha256": None}
    assert dq5_maps._export_directory(tmp_path, rom, options) != dq5_maps._export_directory(
        tmp_path, rom, {**options, key: value},
    )


def test_atomic_output_preserves_previous_file_on_failure(tmp_path: Path) -> None:
    destination = tmp_path / "map.png"
    destination.write_bytes(b"previous image")
    with pytest.raises(OSError, match="interrupted"):
        with dq5_maps._atomic_destination(destination) as temporary:
            temporary.write_bytes(b"incomplete image")
            raise OSError("interrupted")
    assert destination.read_bytes() == b"previous image"
    assert list(tmp_path.iterdir()) == [destination]
    with dq5_maps._atomic_destination(destination) as temporary:
        temporary.write_bytes(b"complete image")
    assert destination.read_bytes() == b"complete image"
    assert list(tmp_path.iterdir()) == [destination]


def test_cli_exports_native_images_and_isolated_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rom = RomImage(b"", "test", "a" * 32)
    header = MapHeader(5, 0, 0x188000, 1, 1, 1, 0, 0, 0, 10)
    decoded = DecodedFloor(header, bytes(0x20000), bytes(0x10000), bytes(512), 1)
    monkeypatch.setattr(dq5_maps.RomImage, "load", lambda *arguments: rom)
    monkeypatch.setattr(dq5_maps, "map_catalog", lambda source: (header,))
    monkeypatch.setattr(dq5_maps, "decode_floor", lambda *arguments, **options: decoded)
    monkeypatch.setattr(dq5_maps, "treasures_for_floor", lambda *arguments, **options: ())
    arguments = ["dq5_maps.py", "--rom", "owned.sfc", "--area", "05", "--output", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", arguments)
    assert dq5_maps.main() == 0
    first = next(tmp_path.rglob("maps.json"))
    manifest = json.loads(first.read_text(encoding="utf-8"))
    assert manifest["decoder_version"] == dq5_maps.DECODER_VERSION
    assert manifest["maps"][0]["pixel_width"] == 8
    assert manifest["maps"][0]["pixel_height"] == 8
    assert (first.parent / manifest["maps"][0]["image"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (first.parent / "treasures.csv").is_file()
    original_manifest = first.read_bytes()
    monkeypatch.setattr(sys, "argv", [*arguments, "--layer", "base"])
    assert dq5_maps.main() == 0
    assert len(list(tmp_path.rglob("maps.json"))) == 2
    assert first.read_bytes() == original_manifest