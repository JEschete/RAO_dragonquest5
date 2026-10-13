"""Headless acceptance rig: the translated cartridge in a private Snes9x core with scripted joypad input.

Development and test use only. It never talks to RetroArch, never writes a save file, and the plugin
runtime does not import it. A save is copied into the private core's memory; patches change only the
private in-memory cartridge copy, which lets a test walk the party onto any floor.
"""
from __future__ import annotations

import ctypes
from pathlib import Path

from PIL import Image

if __package__:
    from .dq5_core import (AudioBatchCallback, AudioCallback, ENGLISH_MD5S, EnvironmentCallback, GameInfo,
                           InputPollCallback, InputStateCallback, VideoCallback, snapshot_blocks)
    from .dq5_rom import RomImage, lorom_offset
else:
    from dq5_core import (AudioBatchCallback, AudioCallback, ENGLISH_MD5S, EnvironmentCallback, GameInfo,
                          InputPollCallback, InputStateCallback, VideoCallback, snapshot_blocks)
    from dq5_rom import RomImage, lorom_offset


BUTTONS = {"b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6, "right": 7,
           "a": 8, "x": 9, "l": 10, "r": 11}
FIELD_UPDATE = 0x8926
# The Alcapa church door ($2A:E18A) is the exit a test rewrites to arrive somewhere else.
CHURCH_EXIT = 0x2AE18A
# Frames and buttons from power-on to file 1 standing in the field; the core is deterministic.
BOOT_SCRIPT = ((600, "start"), (300, ""), (600, "start"), (120, "start"), (120, ""), (1500, "start"),
               (200, "a"), (200, "a"), (300, "a"), (120, "a"), (120, "b"), (30, "b"), (30, ""))


def teleport_patch(area: int, floor: int, xcoord: int, ycoord: int, level: int = 1) -> dict[int, bytes]:
    """Cartridge patch that makes the church exit commit the party to this floor cell."""
    if not all(0 <= value <= 255 for value in (area, floor, xcoord, ycoord, level)):
        raise ValueError("Exit record fields are single bytes")
    return {CHURCH_EXIT + 6: bytes((area, floor, xcoord, ycoord, 1, level))}


class Lab:
    def __init__(self, rom: RomImage, core: Path, *, save: bytes | None = None,
                 patches: dict[int, bytes] | None = None) -> None:
        if rom.md5 not in ENGLISH_MD5S:
            raise ValueError("The acceptance rig runs the translated DeJap cartridge only")
        image = bytearray(rom.data)
        for address, data in (patches or {}).items():
            offset = lorom_offset(address)
            image[offset:offset + len(data)] = data
        self.library = ctypes.CDLL(str(core.resolve()))
        self._rom = ctypes.create_string_buffer(bytes(image), len(image))
        self._held: frozenset[int] = frozenset()
        self._frame: tuple[bytes, int, int, int] | None = None
        self._format = 0
        self._loaded = False
        self._callbacks = (EnvironmentCallback(self._environment), VideoCallback(self._video),
                           AudioCallback(lambda left, right: None), AudioBatchCallback(lambda data, frames: frames),
                           InputPollCallback(lambda: None), InputStateCallback(self._input))
        library = self.library
        library.retro_load_game.restype = ctypes.c_bool
        library.retro_load_game.argtypes = [ctypes.POINTER(GameInfo)]
        library.retro_serialize_size.restype = ctypes.c_size_t
        library.retro_serialize.restype = library.retro_unserialize.restype = ctypes.c_bool
        library.retro_serialize.argtypes = library.retro_unserialize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        library.retro_get_memory_data.restype = ctypes.c_void_p
        library.retro_get_memory_data.argtypes = library.retro_get_memory_size.argtypes = [ctypes.c_uint]
        library.retro_get_memory_size.restype = ctypes.c_size_t
        for setter, callback in zip(("retro_set_environment", "retro_set_video_refresh", "retro_set_audio_sample",
                                     "retro_set_audio_sample_batch", "retro_set_input_poll",
                                     "retro_set_input_state"), self._callbacks, strict=True):
            getattr(library, setter)(callback)
        library.retro_init()
        game = GameInfo(b"DQ5_DeJap.sfc", ctypes.cast(self._rom, ctypes.c_void_p), len(image), None)
        if not library.retro_load_game(ctypes.byref(game)):
            library.retro_deinit()
            raise ValueError("Snes9x refused the translated ROM")
        self._loaded = True
        if save is not None:
            if len(save) > library.retro_get_memory_size(0):
                raise ValueError("Save data does not fit the private cartridge RAM")
            ctypes.memmove(library.retro_get_memory_data(0), save, len(save))

    def _environment(self, command: int, data: int) -> bool:
        if command == 3:
            ctypes.cast(data, ctypes.POINTER(ctypes.c_bool))[0] = True
            return True
        if command == 10:
            self._format = ctypes.cast(data, ctypes.POINTER(ctypes.c_uint))[0]
            return True
        if command == 17:
            ctypes.cast(data, ctypes.POINTER(ctypes.c_bool))[0] = False
            return True
        return command in (6, 11, 16, 18, 35, 36)

    def _video(self, data: int, width: int, height: int, pitch: int) -> None:
        if data:
            self._frame = (ctypes.string_at(data, pitch * height), width, height, pitch)

    def _input(self, port: int, device: int, index: int, identity: int) -> int:
        if port or device != 1:
            return 0
        return sum(1 << button for button in self._held) if identity == 256 else int(identity in self._held)

    def __enter__(self) -> Lab:
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._loaded:
            self.library.retro_unload_game()
            self.library.retro_deinit()
            self._loaded = False

    def run(self, frames: int, *buttons: str) -> None:
        if not self._loaded or not 0 <= frames <= 36000:
            raise ValueError("Private frame budget is invalid")
        self._held = frozenset(BUTTONS[button] for button in buttons)
        for _ in range(frames):
            self.library.retro_run()
        self._held = frozenset()

    def tap(self, button: str, wait: int = 40, hold: int = 6) -> None:
        self.run(hold, button)
        self.run(wait)

    def boot(self) -> None:
        """Run from power-on to the loaded file standing in the field."""
        for wait, button in BOOT_SCRIPT:
            self.run(wait)
            if button:
                self.run(4, button)
                self.run(20)
        ram = self.ram
        if int.from_bytes(ram[0x1944:0x1946], "little") != FIELD_UPDATE or not ram[0x201D]:
            raise ValueError("The boot script did not reach a loaded field")

    @property
    def ram(self) -> bytes:
        return ctypes.string_at(self.library.retro_get_memory_data(2), 0x20000)

    @property
    def video_ram(self) -> bytes:
        return ctypes.string_at(self.library.retro_get_memory_data(3), self.library.retro_get_memory_size(3))

    def poke(self, offset: int, data: bytes) -> None:
        if not 0 <= offset <= 0x20000 - len(data):
            raise ValueError("Private WRAM write leaves the buffer")
        ctypes.memmove(self.library.retro_get_memory_data(2) + offset, data, len(data))

    def state(self) -> bytes:
        size = self.library.retro_serialize_size()
        buffer = ctypes.create_string_buffer(size)
        if not self.library.retro_serialize(buffer, size):
            raise ValueError("Snes9x refused state serialization")
        snapshot_blocks(buffer.raw)
        return buffer.raw

    def restore(self, data: bytes) -> None:
        buffer = ctypes.create_string_buffer(data, len(data))
        if not self.library.retro_unserialize(buffer, len(data)):
            raise ValueError("Snes9x refused the private state")
        self.run(1)

    def frame(self) -> Image.Image:
        """Latest video frame at native size."""
        if self._frame is None:
            raise ValueError("No video frame has been produced")
        data, width, height, pitch = self._frame
        mode = {2: "BGR;16", 1: "BGRX"}.get(self._format, "BGR;15")
        return Image.frombuffer("RGB", (width, height), data, "raw", mode, pitch, 1).copy()

    def walk(self, button: str, cells: int) -> None:
        """Hold a direction for whole cells; the field moves one 8-pixel cell every eight frames."""
        for _ in range(cells):
            self.run(8, button)
            self.run(1)

    def command(self, column: int, row: int) -> None:
        """Open the field command window and confirm the entry at this column (0-1) and row (0-3).

        Call it right after a movement input: once the party idles, the first press only
        dismisses the status display the game shows while standing still.
        """
        self.tap("a", wait=64)
        for button, count in (("right", column), ("down", row)):
            for _ in range(count):
                self.tap(button, wait=12, hold=4)
        self.tap("a", wait=90)
