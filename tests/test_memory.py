from __future__ import annotations

import importlib

import pytest


class Reader:
    def __init__(self, *, truncated: bool = False, changing: bool = False) -> None:
        self.calls: list[tuple[int, int]] = []
        self.truncated = truncated
        self.changing = changing

    def read_memory(self, address: int, size: int) -> bytes:
        self.calls.append((address, size))
        if self.truncated:
            return bytes(size - 1)
        return bytes((1 if self.changing and len(self.calls) > 4 else 0,)) * size


def test_capture_is_bounded_and_tracks_actual_regions(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    reader = Reader()
    snapshot = module.capture(reader)
    assert len(snapshot.ram) == 0x20000
    assert max(size for address, size in reader.calls) <= 4096
    assert len(reader.calls) == len(module.REGIONS) + len(module.GUARDS)
    assert snapshot.has_range(0x2040, 42)
    assert not snapshot.has_range(0xC000, 8)


@pytest.mark.parametrize("options", [{"truncated": True}, {"changing": True}])
def test_incomplete_or_mixed_capture_is_rejected(plugin_package: str, options: dict[str, bool]) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    with pytest.raises(ValueError):
        module.capture(Reader(**options))


def test_changing_combat_header_is_rejected(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")

    class ChangingBattle(Reader):
        def read_memory(self, address: int, size: int) -> bytes:
            data = super().read_memory(address, size)
            return bytes((1,)) + data[1:] if address == 0x7E1000 and size == 0x20 else data

    with pytest.raises(ValueError, match="state changed"):
        module.capture(ChangingBattle())


def test_adaptive_reader_uses_primary_until_descriptors_are_missing(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")

    class Primary(Reader):
        unavailable = False

        def read_memory(self, address: int, size: int) -> bytes:
            if self.unavailable:
                self.calls.append((address, size))
                raise RuntimeError("RetroArch core has no descriptor for that address")
            return super().read_memory(address, size)

    primary = Primary()
    fallback = Reader()
    adaptive = module.AdaptiveSnesMemoryReader(primary, lambda source: fallback)
    assert adaptive.read_memory(0x7E2040, 42) == bytes(42)
    assert not adaptive.using_core_ram
    primary.unavailable = True
    assert adaptive.read_memory(0x7E2040, 42) == bytes(42)
    assert adaptive.using_core_ram
    assert adaptive.read_memory(0x7E2040, 42) == bytes(42)
    assert len(primary.calls) == 2
    assert len(fallback.calls) == 2
    adaptive.close()
    assert not adaptive.using_core_ram


def test_adaptive_reader_does_not_hide_unrelated_transport_errors(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")

    class Offline(Reader):
        def read_memory(self, address: int, size: int) -> bytes:
            raise RuntimeError("network unavailable")

    def forbidden_fallback(source):
        raise AssertionError("An unrelated transport error must not change the reader")

    adaptive = module.AdaptiveSnesMemoryReader(Offline(), forbidden_fallback)
    with pytest.raises(RuntimeError, match="network unavailable"):
        adaptive.read_memory(0x7E2040, 42)


def test_core_ram_reader_maps_wram_and_uses_256_byte_chunks(plugin_package: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    reader = module.CoreRamReader("127.0.0.1", 55356, 0.4)
    commands = []

    def response(command: str) -> str:
        commands.append(command)
        verb, address, size = command.split()
        return f"{verb} {address.upper()} " + " ".join("5A" for _ in range(int(size)))

    monkeypatch.setattr(reader, "_request", response)
    assert reader.read_memory(0x7F0100, 300) == bytes((0x5A,)) * 300
    assert commands == ["READ_CORE_RAM 10100 256", "READ_CORE_RAM 10200 44"]


@pytest.mark.parametrize("response", [
    "READ_CORE_RAM 2040 -1", "READ_CORE_RAM 2041 00", "READ_CORE_RAM 2040",
    "READ_CORE_RAM 2040 GG", "READ_CORE_RAM 2040 100", "READ_CORE_MEMORY 2040 00",
])
def test_core_ram_reader_rejects_invalid_replies(plugin_package: str, monkeypatch: pytest.MonkeyPatch,
                                               response: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    reader = module.CoreRamReader("127.0.0.1", 55356, 0.4)
    closed = []
    monkeypatch.setattr(reader, "close", lambda: closed.append(True))
    monkeypatch.setattr(reader, "_request", lambda command: response)
    with pytest.raises(RuntimeError):
        reader.read_memory(0x7E2040, 1)
    assert closed == [True]


def test_adaptive_reader_discards_failed_fallback_and_recovers_on_fresh_socket(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")

    class Primary(Reader):
        def read_memory(self, address: int, size: int) -> bytes:
            raise RuntimeError("Core has no descriptor")

    class Fallback(Reader):
        failed = False
        closed = False

        def read_memory(self, address: int, size: int) -> bytes:
            if self.failed:
                raise RuntimeError("Malformed late core-RAM packet")
            return super().read_memory(address, size)

        def close(self) -> None:
            self.closed = True

    created = []

    def factory(source):
        fallback = Fallback()
        created.append(fallback)
        return fallback

    adaptive = module.AdaptiveSnesMemoryReader(Primary(), factory)
    assert adaptive.read_memory(0x7E2040, 1) == bytes(1)
    created[0].failed = True
    with pytest.raises(RuntimeError, match="late"):
        adaptive.read_memory(0x7E2040, 1)
    assert created[0].closed and not adaptive.using_core_ram
    assert adaptive.read_memory(0x7E2040, 1) == bytes(1)
    assert len(created) == 2 and adaptive.using_core_ram
    adaptive.close()