from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock
from time import monotonic

from ..scripts.dq5_native import NativeMachine
from ..scripts.dq5_rom import RomImage
from .battle import Battle
from .state import PartyState


@dataclass(frozen=True, slots=True)
class AttackEstimate:
    member: str
    enemy: str
    enemy_slot: int
    minimum: int
    maximum: int
    average: float
    samples: int


def native_attack_damage(rom: RomImage, snapshot: bytes, attacker: int, defender: int, seed: int) -> int:
    if (len(snapshot) != 0x20000 or not 0 <= attacker < 8 or not 0 <= defender < 16
            or not 0 <= seed <= 0xFFFF):
        raise ValueError("Native attack evaluation requires bounded combatants and complete WRAM")
    machine = NativeMachine(rom, max_steps=20000, timeout=0.1)
    machine.bus.ram[:] = snapshot
    machine.cpu.dbr = 0x20
    machine.cpu.p = 0x34
    machine.bus.write_word(0x075B, seed)
    machine.bus[0x075D] = seed & 0xFF
    machine.bus[0x10F5] = attacker
    machine.bus[0x10F6] = 0x80 | defender
    machine.bus.write_word(0x10EC, 0)
    machine.call(0x20AF6C)
    return machine.bus.word(0x10EC)


class CombatAdvice:
    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future[tuple[AttackEstimate, ...]] | None = None
        self._cancel = Event()
        self._lock = Lock()
        self._progress = (0, 0)
        self._error = ""

    @property
    def running(self) -> bool:
        return self._future is not None and not self._future.done()

    @property
    def progress(self) -> tuple[int, int]:
        with self._lock:
            return self._progress

    @property
    def error(self) -> str:
        self.result()
        return self._error

    def result(self) -> tuple[AttackEstimate, ...]:
        if self._future is None or not self._future.done():
            return ()
        try:
            return self._future.result()
        except (OSError, ValueError, RuntimeError) as error:
            self._error = str(error)
            return ()

    def cancel(self) -> None:
        self._cancel.set()
        if self._future is not None:
            self._future.cancel()

    def close(self) -> None:
        self.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = None
        self._future = None

    def start(self, snapshot: bytes, party: PartyState, battle: Battle) -> None:
        if self.running or not battle.active or battle.arena:
            return
        active = tuple(member for member in party.companions if member.role == "active")
        enemies = tuple(enemy for enemy in battle.enemies if enemy.alive and enemy.hp > 0)
        if not active or not enemies:
            return
        self._cancel = Event()
        self._error = ""
        with self._lock:
            self._progress = (0, len(active) * len(enemies) * 4)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="DQ5-combat")
        self._future = self._executor.submit(self._calculate, snapshot, active, enemies, self._cancel)

    def _calculate(self, snapshot: bytes, members: tuple, enemies: tuple,
                   cancellation: Event) -> tuple[AttackEstimate, ...]:
        deadline = monotonic() + 8
        estimates = []
        for attacker, member in enumerate(members):
            for enemy in enemies:
                amounts = []
                for seed in (1, 0x2345, 0x789A, 0xCDEF):
                    if cancellation.is_set():
                        return ()
                    if monotonic() >= deadline:
                        raise ValueError("Native attack comparison reached its total time limit")
                    amounts.append(native_attack_damage(self.rom, snapshot, attacker, enemy.slot, seed))
                    with self._lock:
                        completed, total = self._progress
                        self._progress = completed + 1, total
                estimates.append(AttackEstimate(member.name, enemy.name, enemy.slot,
                                                min(amounts), max(amounts), sum(amounts) / len(amounts), len(amounts)))
        return tuple(estimates)