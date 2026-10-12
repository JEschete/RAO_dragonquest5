from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import struct
from time import monotonic

if __package__:
    from .dq5_rom import RomImage
else:
    from dq5_rom import RomImage


ENGLISH_MD5S = frozenset(("a1222de3d989fdafd3311f37d89cd025", "5651c58a1c87c42f6b91519969658a88"))
MAX_STATE_BYTES = 0x400000
EnvironmentCallback = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint, ctypes.c_void_p)
VideoCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_size_t)
AudioCallback = ctypes.CFUNCTYPE(None, ctypes.c_int16, ctypes.c_int16)
AudioBatchCallback = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.POINTER(ctypes.c_int16), ctypes.c_size_t)
InputPollCallback = ctypes.CFUNCTYPE(None)
InputStateCallback = ctypes.CFUNCTYPE(ctypes.c_int16, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)


class SystemInfo(ctypes.Structure):
    _fields_ = [("library_name", ctypes.c_char_p), ("library_version", ctypes.c_char_p),
                ("valid_extensions", ctypes.c_char_p), ("need_fullpath", ctypes.c_bool),
                ("block_extract", ctypes.c_bool)]


class GameInfo(ctypes.Structure):
    _fields_ = [("path", ctypes.c_char_p), ("data", ctypes.c_void_p),
                ("size", ctypes.c_size_t), ("meta", ctypes.c_char_p)]


def snapshot_blocks(data: bytes) -> dict[str, tuple[int, int]]:
    header_end = data.find(b"\n", 0, 32)
    if header_end < 0 or not data.startswith(b"#!s9xsnp:") or len(data) > MAX_STATE_BYTES:
        raise ValueError("Unsupported Snes9x snapshot header or size")
    version = data[len(b"#!s9xsnp:"):header_end]
    if not version.isdigit() or not 6 <= int(version) <= 14:
        raise ValueError("Unsupported Snes9x snapshot version")
    position = header_end + 1
    result = {}
    for _ in range(64):
        if position == len(data) or not any(data[position:]):
            return result
        header = data[position:position + 11]
        if len(header) != 11 or header[3:4] != b":" or header[10:11] != b":":
            raise ValueError("Malformed Snes9x snapshot block")
        name = header[:3].decode("ascii")
        if not name.isupper() or name in result:
            raise ValueError("Invalid or repeated Snes9x snapshot block")
        if header[4:5] == b"-":
            size = int.from_bytes(header[6:10], "big")
        elif header[4:10].isdigit():
            size = int(header[4:10])
        else:
            raise ValueError("Malformed Snes9x snapshot block length")
        position += 11
        if size <= 0 or position + size > len(data):
            raise ValueError("Snes9x snapshot block leaves its buffer")
        result[name] = (position, size)
        position += size
    raise ValueError("Snes9x snapshot exceeded its block limit")


class PrivateSnesCore:
    def __init__(self, library: Path, rom: RomImage) -> None:
        if rom.md5 not in ENGLISH_MD5S:
            raise ValueError("Private SNES execution requires a supported translated DeJap ROM")
        self.library = ctypes.CDLL(str(library.resolve()))
        self._initialized = False
        self._loaded = False
        self._rom_buffer = ctypes.create_string_buffer(rom.data)
        self._callbacks = (
            EnvironmentCallback(self._environment),
            VideoCallback(lambda data, width, height, pitch: None),
            AudioCallback(lambda left, right: None),
            AudioBatchCallback(lambda data, frames: frames),
            InputPollCallback(lambda: None),
            InputStateCallback(lambda port, device, index, identity: 0),
        )
        signatures = {
            "retro_api_version": (ctypes.c_uint, ()),
            "retro_get_system_info": (None, (ctypes.POINTER(SystemInfo),)),
            "retro_set_environment": (None, (EnvironmentCallback,)),
            "retro_set_video_refresh": (None, (VideoCallback,)),
            "retro_set_audio_sample": (None, (AudioCallback,)),
            "retro_set_audio_sample_batch": (None, (AudioBatchCallback,)),
            "retro_set_input_poll": (None, (InputPollCallback,)),
            "retro_set_input_state": (None, (InputStateCallback,)),
            "retro_init": (None, ()),
            "retro_deinit": (None, ()),
            "retro_load_game": (ctypes.c_bool, (ctypes.POINTER(GameInfo),)),
            "retro_unload_game": (None, ()),
            "retro_run": (None, ()),
            "retro_serialize_size": (ctypes.c_size_t, ()),
            "retro_serialize": (ctypes.c_bool, (ctypes.c_void_p, ctypes.c_size_t)),
            "retro_unserialize": (ctypes.c_bool, (ctypes.c_void_p, ctypes.c_size_t)),
            "retro_get_memory_data": (ctypes.c_void_p, (ctypes.c_uint,)),
            "retro_get_memory_size": (ctypes.c_size_t, (ctypes.c_uint,)),
        }
        for name, (return_type, arguments) in signatures.items():
            function = getattr(self.library, name)
            function.restype = return_type
            function.argtypes = list(arguments)
        if self.library.retro_api_version() != 1:
            raise ValueError("Unsupported libretro API")
        info = SystemInfo()
        self.library.retro_get_system_info(ctypes.byref(info))
        self.name = (info.library_name or b"").decode("ascii")
        self.version = (info.library_version or b"").decode("ascii")
        if self.name != "Snes9x" or info.need_fullpath:
            raise ValueError("Private execution requires the in-memory Snes9x core")
        setters = ("retro_set_environment", "retro_set_video_refresh", "retro_set_audio_sample",
                   "retro_set_audio_sample_batch", "retro_set_input_poll", "retro_set_input_state")
        for setter, callback in zip(setters, self._callbacks, strict=True):
            getattr(self.library, setter)(callback)
        try:
            self.library.retro_init()
            self._initialized = True
            game = GameInfo(b"DQ5_DeJap.sfc", ctypes.cast(self._rom_buffer, ctypes.c_void_p), len(rom.data), None)
            if not self.library.retro_load_game(ctypes.byref(game)):
                raise ValueError("Snes9x refused the translated ROM")
            self._loaded = True
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _environment(command: int, data: int) -> bool:
        if command == 3:
            ctypes.cast(data, ctypes.POINTER(ctypes.c_bool))[0] = True
            return True
        if command == 10:
            return ctypes.cast(data, ctypes.POINTER(ctypes.c_uint))[0] in (0, 1, 2)
        if command == 17:
            ctypes.cast(data, ctypes.POINTER(ctypes.c_bool))[0] = False
            return True
        return command in (6, 11, 16, 18, 35, 36)

    def __enter__(self) -> PrivateSnesCore:
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._loaded:
            self.library.retro_unload_game()
            self._loaded = False
        if self._initialized:
            self.library.retro_deinit()
            self._initialized = False

    def run_frames(self, count: int, *, timeout: float = 3) -> None:
        if not self._loaded or not 1 <= count <= 3600 or not 0 < timeout <= 30:
            raise ValueError("Private SNES frame budget is invalid")
        deadline = monotonic() + timeout
        for _ in range(count):
            if monotonic() >= deadline:
                raise ValueError("Private SNES execution exceeded its frame time budget")
            self.library.retro_run()

    def memory(self, identity: int) -> bytes:
        size = self.library.retro_get_memory_size(identity)
        pointer = self.library.retro_get_memory_data(identity)
        if not self._loaded or not pointer or not 0 < size <= MAX_STATE_BYTES:
            raise ValueError("Private SNES memory is unavailable")
        return ctypes.string_at(pointer, size)

    def state(self) -> bytes:
        size = self.library.retro_serialize_size()
        if not self._loaded or not 0 < size <= MAX_STATE_BYTES:
            raise ValueError("Private SNES state size is invalid")
        buffer = ctypes.create_string_buffer(size)
        if not self.library.retro_serialize(buffer, size):
            raise ValueError("Snes9x refused state serialization")
        result = buffer.raw
        blocks = snapshot_blocks(result)
        if blocks.get("RAM", (0, 0))[1] != 0x20000 or blocks.get("REG", (0, 0))[1] != 16:
            raise ValueError("Snes9x state does not expose the verified RAM/register layout")
        return result

    def restore(self, data: bytes) -> None:
        snapshot_blocks(data)
        buffer = ctypes.create_string_buffer(data)
        if not self._loaded or not self.library.retro_unserialize(buffer, len(data)):
            raise ValueError("Snes9x refused the private state")

    def call(self, address: int, snapshot: bytes, *, long_return: bool = False,
             data_bank: int = 0x7E, flags: int = 0x24,
             frame_limit: int = 4, timeout: float = 1, enable_nmi: bool = False) -> bytes:
        if (not 0 <= address <= 0xFFFFFF or address & 0xFFFF < 0x8000
                or len(snapshot) != 0x20000 or not 0 <= data_bank <= 255
                or not 0 <= flags <= 255 or not 1 <= frame_limit <= 3600 or not 0 < timeout <= 30):
            raise ValueError("Private native-call inputs or budget are invalid")
        state = bytearray(self.state())
        blocks = snapshot_blocks(state)
        ram_start, _ = blocks["RAM"]
        ram = bytearray(snapshot)
        ram[0x1E00:0x1E09] = bytes.fromhex("E220A9A58D101E80FE")
        ram[0x1E10] = 0
        stack = 0x1FE0
        ram[stack + 1:stack + 3] = bytes.fromhex("FF1D")
        if long_return:
            ram[stack + 3] = 0x7E
        state[ram_start:ram_start + len(ram)] = ram
        register_start, register_size = blocks["REG"]
        state[register_start:register_start + register_size] = struct.pack(
            ">BBHHHHHHH", address >> 16, data_bank, flags, 0, 0, stack, 0, 0, address & 0xFFFF)
        cpu_start, cpu_size = blocks["CPU"]
        if cpu_size < 6:
            raise ValueError("Snes9x CPU block cannot expose its interrupt state")
        state[cpu_start + cpu_size - 6:cpu_start + cpu_size] = bytes(6)
        io_start, io_size = blocks["FIL"]
        if io_size != 0x8000:
            raise ValueError("Snes9x I/O shadow has an unsupported layout")
        state[io_start + 0x4200] = 0x81 if enable_nmi else 0
        self.restore(bytes(state))
        deadline = monotonic() + timeout
        for _ in range(frame_limit):
            if monotonic() >= deadline:
                raise ValueError("Native Snes9x call exceeded its time budget")
            self.library.retro_run()
            result = self.memory(2)
            if result[0x1E10] == 0xA5:
                return result
        current = self.state()
        register_start, register_size = snapshot_blocks(current)["REG"]
        registers = struct.unpack(">BBHHHHHHH", current[register_start:register_start + register_size])
        raise ValueError(f"Native Snes9x call reached its frame limit at {registers[0]:02X}:{registers[-1]:04X} "
                 f"(round {result[0x101A]}, remaining {result[0x1012]}, "
                 f"flags ${result[0x1015]:02X}, return marker ${result[0x1E10]:02X})")

def main() -> int:
    parser = argparse.ArgumentParser(description="Check isolated translated-ROM Snes9x execution")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    options = parser.parse_args()
    rom = RomImage.load(options.rom)
    with PrivateSnesCore(options.core, rom) as core:
        core.run_frames(2)
        initial = core.memory(2)
        state = core.state()
        core.run_frames(2)
        core.restore(state)
        if core.memory(2) != initial:
            raise ValueError("Private Snes9x restore did not preserve WRAM")
        blocks = snapshot_blocks(state)
        offset, size = blocks["REG"]
        registers = struct.unpack(">BBHHHHHHH", state[offset:offset + size])
        report = {"core": core.name, "version": core.version, "rom": rom.variant,
                  "wram_bytes": len(initial), "state_bytes": len(state),
                  "blocks": tuple(blocks), "pc": f"{registers[0]:02X}:{registers[-1]:04X}",
                  "restored": True}
        working = bytearray(initial)
        working[0x21A1:0x21A5] = bytes((0xFF,)) * 4
        returned = core.call(0x00A957, bytes(working), long_return=True)
        if returned[0x21A1:0x21A5] != bytes(4):
            raise ValueError("Snes9x native routine disagrees with the verified private-CPU result")
        report["native_call"] = True
        working = bytearray(returned)
        working[0x38] = working[0x42] = 0
        working[0x2041] = 0x80
        working[0x2042:0x2044] = (567).to_bytes(2, "little")
        returned = core.call(0x218AFC, bytes(working), data_bank=0x21, flags=0x34)
        if int.from_bytes(returned[0x46:0x49], "little") != 567:
            raise ValueError("Snes9x native accessor disagrees with the known physical-party HP")
        report["native_accessor"] = True
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())