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
    assert len(reader.calls) == len(module.REGIONS) + len(module.GUARDS) + 1
    assert snapshot.has_range(0x2040, 42)
    assert not snapshot.has_range(0xC000, 8)
    assert not any(start <= 0xBA < start + size for start, size in module.GUARDS)
    assert not any(start <= 0xB9 < start + size for start, size in module.GUARDS)
    assert any(start <= 0xBB < start + size for start, size in module.GUARDS)


@pytest.mark.parametrize("coordinates", [((0xB6, 10), (0xB8, 20)), ((0xC1, 6), (0xC2, 7), (0xC3, 2))])
def test_walking_updates_position_without_rejecting_capture(plugin_package: str, coordinates) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")

    class Walking(Reader):
        def read_memory(self, address: int, size: int) -> bytes:
            data = bytearray(super().read_memory(address, size))
            if address == 0x7E00B6 and size == 14:
                for offset, value in coordinates:
                    data[offset - 0xB6] = value
            return bytes(data)

    result = module.capture(Walking())
    assert all(result.ram[offset] == value for offset, value in coordinates)
    assert not any(start <= offset < start + size for start, size in module.GUARDS
                   for offset in (0xB6, 0xB7, 0xB8, 0xB9, 0xC1, 0xC2, 0xC3))


def test_position_sample_rejects_map_identity_changes(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")

    class Transition(Reader):
        def read_memory(self, address: int, size: int) -> bytes:
            data = bytearray(super().read_memory(address, size))
            if address == 0x7E00B6 and size == 14:
                data[6] = 1
            return bytes(data)

    with pytest.raises(ValueError, match="identity/dimensions changed"):
        module.capture(Transition())


def test_capture_with_retry_recovers_once_from_a_coherence_race(plugin_package: str,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    capture = module.capture
    attempts = []

    def flaky(memory, *, live_map: bool = False):
        attempts.append(None)
        if len(attempts) == 1:
            raise ValueError("DQ5 state changed while the snapshot was being read")
        return capture(memory, live_map=live_map)

    monkeypatch.setattr(module, "capture", flaky)
    snapshot = module.capture_with_retry(Reader())
    assert len(snapshot.ram) == 0x20000 and len(attempts) == 2


def test_capture_with_retry_does_not_hide_persistent_or_unrelated_failures(plugin_package: str,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    attempts = []

    def failing(memory, *, live_map: bool = False):
        attempts.append(None)
        raise ValueError("invalid native floor dimensions")

    monkeypatch.setattr(module, "capture", failing)
    with pytest.raises(ValueError, match="invalid native floor dimensions"):
        module.capture_with_retry(Reader())
    assert len(attempts) == 1


def test_capture_with_retry_logs_coherence_races_only_when_enabled(plugin_package: str,
                                                                    monkeypatch: pytest.MonkeyPatch,
                                                                    caplog: pytest.LogCaptureFixture) -> None:
    import logging

    module = importlib.import_module(f"{plugin_package}.game.memory")
    capture = module.capture
    attempts = []

    def once_unstable(memory, *, live_map: bool = False):
        attempts.append(None)
        if len(attempts) == 1:
            raise ValueError("DQ5 state changed while the snapshot was being read at $7E:00BA")
        return capture(memory, live_map=live_map)

    monkeypatch.setattr(module, "capture", once_unstable)
    with caplog.at_level(logging.WARNING, logger=module.__name__):
        module.capture_with_retry(Reader(), diagnostics=False)
        assert not caplog.records
        attempts.clear()
        module.capture_with_retry(Reader(), diagnostics=True)
    assert len(attempts) == 2
    assert len(caplog.records) == 1 and "$7E:00BA" in caplog.records[0].message


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


def test_core_ram_reader_maps_wram_and_uses_bounded_large_chunks(plugin_package: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(f"{plugin_package}.game.memory")
    reader = module.CoreRamReader("127.0.0.1", 55356, 0.4)
    commands = []

    def response(command: str) -> str:
        commands.append(command)
        verb, address, size = command.split()
        return f"{verb} {address.upper()} " + " ".join("5A" for _ in range(int(size)))

    monkeypatch.setattr(reader, "_request", response)
    assert reader.read_memory(0x7E0100, 9000) == bytes((0x5A,)) * 9000
    assert commands == ["READ_CORE_RAM 100 4096", "READ_CORE_RAM 1100 4096", "READ_CORE_RAM 2100 808"]


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