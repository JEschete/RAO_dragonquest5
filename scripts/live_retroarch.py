from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from time import monotonic

if __package__:
    from .dq5_rom import RomImage
else:
    from dq5_rom import RomImage


ENGLISH_ROMS = frozenset(("a1222de3d989fdafd3311f37d89cd025", "5651c58a1c87c42f6b91519969658a88"))

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTALL = Path("F:/Emulators/LaunchBox/Emulators/RetroArch")
DEFAULT_ROM = ROOT / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).sfc"
DEFAULT_OUTPUT = ROOT / "native-maps/diagnostics/live"


def request(port: int, command: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.settimeout(1)
        connection.connect(("127.0.0.1", port))
        connection.send(command.encode("ascii"))
        return connection.recv(65535).decode("ascii", errors="replace").strip()


def launch(install: Path, rom: Path, output: Path, port: int) -> dict[str, object]:
    executable = install / "retroarch.exe"
    core = install / "cores/snes9x_libretro.dll"
    if not executable.is_file() or not core.is_file() or not rom.is_file():
        raise ValueError("RetroArch, Snes9x, and the supplied DeJap cartridge must exist")
    if RomImage.load(rom).md5 not in ENGLISH_ROMS:
        raise ValueError("Live acceptance targets translated DeJap cartridges only")
    try:
        active = request(port, "GET_STATUS")
    except (OSError, TimeoutError):
        active = ""
    if active:
        raise ValueError(f"Test port {port} is already occupied: {active}")
    output.mkdir(parents=True, exist_ok=True)
    saves = output / "saves"
    states = output / "states"
    remaps = output / "remaps"
    saves.mkdir(exist_ok=True)
    states.mkdir(exist_ok=True)
    remaps.mkdir(exist_ok=True)
    original = Path("F:/RASaves") / rom.with_suffix(".srm").name
    save_hash = None
    if original.is_file():
        save_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        destination = saves / original.name
        if not destination.exists():
            shutil.copy2(original, destination)
    settings = {
        "network_cmd_enable": "true", "network_cmd_port": str(port),
        "config_save_on_exit": "false", "cheevos_enable": "false",
        "input_remap_binds_enable": "false", "history_list_enable": "false",
        "input_remapping_directory": remaps.as_posix(), "input_turbo_enable": "false",
        "cheevos_hardcore_mode_enable": "false", "video_fullscreen": "false",
        "video_driver": "gl", "video_shader_enable": "false",
        "video_windowed_fullscreen": "false", "video_windowed_scale": "3",
        "audio_enable": "false", "pause_nonactive": "false",
        "savefile_directory": saves.as_posix(), "savestate_directory": states.as_posix(),
        "sort_savefiles_enable": "false", "sort_savefiles_by_content_enable": "false",
        "sort_savestates_enable": "false", "sort_savestates_by_content_enable": "false",
        "screenshot_directory": output.as_posix(), "log_verbosity": "true",
        "input_driver": "dinput", "input_joypad_driver": "xinput",
        "input_player1_a": "x", "input_player1_b": "z", "input_player1_start": "enter",
        "input_player1_select": "rshift", "input_player1_up": "up",
        "input_player1_down": "down", "input_player1_left": "left", "input_player1_right": "right",
    }
    config = output / "retroarch.cfg"
    config.write_text("".join(f'{key} = "{value}"\n' for key, value in settings.items()), encoding="utf-8")
    with (output / "process.log").open("w", encoding="utf-8") as log_stream:
        process = subprocess.Popen([str(executable), "--verbose", "--config", str(config), "--log-file",
                                    str(output / "retroarch.log"), "-L", str(core), str(rom)], cwd=install,
                                   stdout=log_stream, stderr=subprocess.STDOUT)
    state = {"pid": process.pid, "port": port, "rom": str(rom), "original_save": str(original),
             "original_save_sha256": save_hash, "config": str(config)}
    (output / "session.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def capture(port: int, output: Path) -> dict[str, object]:
    sys.path.insert(0, str(ROOT.parents[1] / "src"))
    sys.path.insert(0, str(ROOT))
    from retroarch_overlay.retroarch import RetroArchClient
    from game.memory import AdaptiveSnesMemoryReader

    status = request(port, "GET_STATUS")
    if not status.startswith("GET_STATUS PLAYING") and not status.startswith("GET_STATUS PAUSED"):
        raise ValueError(f"The test core is not running content: {status}")
    ram = bytearray()
    deadline = monotonic() + 12
    source = RetroArchClient(port=port, timeout=1)
    reader = AdaptiveSnesMemoryReader(source)
    try:
        for offset in range(0, 0x20000, 4096):
            if monotonic() >= deadline:
                raise ValueError("Live WRAM capture exceeded its 12-second limit")
            ram.extend(reader.read_memory(0x7E0000 + offset, 4096))
        transport = "READ_CORE_RAM" if reader.using_core_ram else "READ_CORE_MEMORY"
    finally:
        reader.close()
        source.close()
    output.mkdir(parents=True, exist_ok=True)
    (output / "capture.wram").write_bytes(ram)
    result = {"status": status, "transport": transport, "bytes": len(ram), "party_total": ram[0x201D],
              "active_count": ram[0x201E], "mode": f"{int.from_bytes(ram[0x1944:0x1946], 'little'):04X}",
              "area": ram[0xBC], "floor": ram[0xBD], "era": ram[0x1948],
              "native_frame": ram[0x0993], "controller_bytes": ram[0x20:0x27].hex(),
              "core_snapshot_sha256": hashlib.sha256(ram).hexdigest()}
    (output / "capture.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def press_start(port: int, output: Path, *, button: str = "start") -> dict[str, object]:
    import ctypes
    from ctypes import wintypes

    session = json.loads((output / "session.json").read_text(encoding="utf-8"))
    keys = {"start": (0x0D, 0x1C), "a": (0x58, 0x2D), "b": (0x5A, 0x2C),
            "up": (0x26, 0x48), "down": (0x28, 0x50), "left": (0x25, 0x4B), "right": (0x27, 0x4D)}
    if button not in keys:
        raise ValueError("Only configured single controller buttons are permitted")
    virtual_key, scan_code = keys[button]
    if session["port"] != port or not request(port, "GET_STATUS").startswith("GET_STATUS PLAYING"):
        raise ValueError("The isolated test session is not running")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND

    class KeyboardInput(ctypes.Structure):
        _fields_ = (("virtual_key", wintypes.WORD), ("scan_code", wintypes.WORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t))

    class MouseInput(ctypes.Structure):
        _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG), ("data", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t))

    class InputData(ctypes.Union):
        _fields_ = (("keyboard", KeyboardInput), ("mouse", MouseInput))

    class InputEvent(ctypes.Structure):
        _fields_ = (("kind", wintypes.DWORD), ("data", InputData))

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(InputEvent), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    def send_key(released: bool) -> None:
        flags = 0x08 | (0x02 if released else 0) | (0x01 if button in ("up", "down", "left", "right") else 0)
        event = InputEvent(1, InputData(keyboard=KeyboardInput(0, scan_code, flags, 0, 0)))
        if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError(ctypes.get_last_error(), "Isolated key input was refused by Windows")
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    windows = []

    @callback_type
    def find_window(window, parameter):
        process = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process))
        if process.value == session["pid"] and user32.IsWindowVisible(window):
            windows.append(window)
        return True

    user32.EnumWindows(find_window, 0)
    if not windows:
        raise ValueError("The isolated RetroArch window is unavailable")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    current_thread = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    target_thread = user32.GetWindowThreadProcessId(windows[0], None)
    attached = []
    try:
        for thread in dict.fromkeys((foreground_thread, target_thread)):
            if thread and thread != current_thread and user32.AttachThreadInput(current_thread, thread, True):
                attached.append(thread)
        user32.ShowWindow(windows[0], 9)
        user32.BringWindowToTop(windows[0])
        user32.SetForegroundWindow(windows[0])
    finally:
        for thread in reversed(attached):
            user32.AttachThreadInput(current_thread, thread, False)
    focused_process = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(focused_process))
    if focused_process.value != session["pid"]:
        raise ValueError("Refusing controller input because the isolated emulator does not have focus")
    sys.path.insert(0, str(ROOT.parents[1] / "src"))
    sys.path.insert(0, str(ROOT))
    from retroarch_overlay.retroarch import RetroArchClient
    from game.memory import AdaptiveSnesMemoryReader

    source = RetroArchClient(port=port, timeout=0.4)
    reader = AdaptiveSnesMemoryReader(source)
    if int.from_bytes(reader.read_memory(0x7E1944, 2), "little") not in (0x8926, 0x8952):
        reader.close()
        source.close()
        raise ValueError("The isolated game has not initialized its native frame service")
    initial_frame = reader.read_memory(0x7E0993, 1)[0]
    deadline = monotonic() + 2
    held_frames = 0
    held_controller = b""
    try:
        send_key(False)
        for _ in range(1024):
            current_frame = reader.read_memory(0x7E0993, 1)[0]
            held_frames = (current_frame - initial_frame) & 255
            if held_frames >= 6:
                held_controller = reader.read_memory(0x7E0020, 7)
                break
            if monotonic() >= deadline:
                raise ValueError(f"The isolated core did not advance six frame ticks within its input budget "
                                 f"({initial_frame} -> {current_frame})")
        else:
            raise ValueError("The isolated core did not advance six native frames within its capture budget")
    finally:
        send_key(True)
        reader.close()
        source.close()
    result = capture(port, output)
    result["input"] = f"One {button} press in the isolated test session"
    result["held_native_frames"] = held_frames
    result["held_controller_bytes"] = held_controller.hex()
    return result


def screenshot(port: int, output: Path) -> dict[str, object]:
    session = json.loads((output / "session.json").read_text(encoding="utf-8"))
    if session["port"] != port:
        raise ValueError("Screenshot endpoint does not match the isolated session")
    status = request(port, "GET_STATUS")
    if not any(f"crc32={checksum}" in status.casefold() for checksum in ("6110a1a2", "9400cb3c")):
        raise ValueError("Screenshot requires a running supported translated cartridge")
    existing = set(output.glob("*.png"))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.sendto(b"SCREENSHOT", ("127.0.0.1", port))
    result = capture(port, output)
    images = tuple(path for path in output.glob("*.png") if path not in existing)
    if not images:
        raise ValueError("The isolated core has not produced its requested screenshot")
    result["screenshot"] = str(max(images, key=lambda path: path.stat().st_mtime_ns))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated DQ5 validation: read-only memory and explicit test-session Start")
    parser.add_argument("action", choices=("launch", "status", "capture", "start", "button", "screenshot"))
    parser.add_argument("--button", choices=("start", "a", "b", "up", "down", "left", "right"), default="start")
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=55356)
    arguments = parser.parse_args()
    try:
        result = (launch(arguments.install, arguments.rom, arguments.output, arguments.port)
                  if arguments.action == "launch" else press_start(arguments.port, arguments.output)
                  if arguments.action == "start" else press_start(arguments.port, arguments.output, button=arguments.button)
                  if arguments.action == "button" else capture(arguments.port, arguments.output)
                  if arguments.action == "capture" else screenshot(arguments.port, arguments.output)
                  if arguments.action == "screenshot" else {"status": request(arguments.port, "GET_STATUS")})
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f"DQ5 live validation: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())