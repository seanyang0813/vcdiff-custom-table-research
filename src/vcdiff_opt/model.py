from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

NOOP = 0
ADD = 1
RUN = 2
COPY = 3

TYPE_TO_ID = {"NOOP": NOOP, "ADD": ADD, "RUN": RUN, "COPY": COPY}
ID_TO_TYPE = {value: key for key, value in TYPE_TO_ID.items()}


@dataclass(frozen=True, order=True)
class Atom:
    type_id: int
    size: int
    mode: int = 0

    def __post_init__(self) -> None:
        if self.type_id not in (ADD, RUN, COPY):
            raise ValueError(f"invalid instruction type: {self.type_id}")
        if self.size <= 0:
            raise ValueError(f"instruction size must be positive: {self.size}")
        if self.type_id == COPY:
            if self.mode < 0:
                raise ValueError(f"COPY mode must be nonnegative: {self.mode}")
        elif self.mode != 0:
            raise ValueError("ADD and RUN modes must be zero")

    @property
    def type_name(self) -> str:
        return ID_TO_TYPE[self.type_id]

    def to_dict(self) -> dict[str, int | str]:
        return {"type": self.type_name, "size": self.size, "mode": self.mode}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Atom:
        return cls(TYPE_TO_ID[str(value["type"])], int(value["size"]), int(value.get("mode", 0)))


@dataclass(frozen=True, order=True)
class Pattern:
    atoms: tuple[Atom, ...]

    def __post_init__(self) -> None:
        if len(self.atoms) not in (1, 2):
            raise ValueError("a restricted pattern must contain one or two instructions")
        if any(atom.size > 255 for atom in self.atoms):
            raise ValueError("implicit code-table sizes are single bytes")

    @property
    def width(self) -> int:
        return len(self.atoms)

    def to_dict(self) -> dict[str, Any]:
        return {"atoms": [atom.to_dict() for atom in self.atoms]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Pattern:
        return cls(tuple(Atom.from_dict(atom) for atom in value["atoms"]))

    def label(self) -> str:
        return "+".join(
            f"{atom.type_name}:{atom.size}:{atom.mode}" for atom in self.atoms
        )


@dataclass(frozen=True)
class Instruction:
    position: int
    type_id: int
    size: int
    mode: int = 0
    address: int | None = None
    source_copy: bool | None = None
    run_byte: int | None = None

    def __post_init__(self) -> None:
        Atom(self.type_id, self.size, self.mode)
        if self.position < 0:
            raise ValueError("instruction position must be nonnegative")
        if self.type_id == COPY:
            if self.address is None or self.address < 0:
                raise ValueError("COPY requires a nonnegative address")
            if self.source_copy is None:
                raise ValueError("COPY requires source_copy provenance")
            if self.run_byte is not None:
                raise ValueError("COPY cannot carry a RUN byte")
        elif self.type_id == RUN:
            if self.run_byte is None or not 0 <= self.run_byte <= 255:
                raise ValueError("RUN requires a byte value")
            if self.address is not None or self.source_copy is not None:
                raise ValueError("RUN cannot carry a COPY address")
        else:
            if (
                self.address is not None
                or self.source_copy is not None
                or self.run_byte is not None
            ):
                raise ValueError("ADD cannot carry COPY/RUN payload metadata")

    @property
    def atom(self) -> Atom:
        return Atom(self.type_id, self.size, self.mode)

    @property
    def type_name(self) -> str:
        return ID_TO_TYPE[self.type_id]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "position": self.position,
            "type": self.type_name,
            "size": self.size,
            "mode": self.mode,
        }
        if self.address is not None:
            result["address"] = self.address
        if self.source_copy is not None:
            result["source_copy"] = self.source_copy
        if self.run_byte is not None:
            result["byte"] = self.run_byte
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Instruction:
        return cls(
            position=int(value["position"]),
            type_id=TYPE_TO_ID[str(value["type"])],
            size=int(value["size"]),
            mode=int(value.get("mode", 0)),
            address=None if "address" not in value else int(value["address"]),
            source_copy=value.get("source_copy"),
            run_byte=None if "byte" not in value else int(value["byte"]),
        )


@dataclass(frozen=True)
class WindowTrace:
    index: int
    target_offset: int
    target_length: int
    source_used: bool
    source_position: int
    source_length: int
    instructions: tuple[Instruction, ...]

    def __post_init__(self) -> None:
        if min(
            self.index,
            self.target_offset,
            self.target_length,
            self.source_position,
            self.source_length,
        ) < 0:
            raise ValueError("window fields must be nonnegative")
        if not self.source_used and (self.source_position != 0 or self.source_length != 0):
            raise ValueError("a source-free window must have zero source range")
        expected = 0
        for instruction in self.instructions:
            if instruction.position != expected:
                raise ValueError(
                    f"window {self.index} has a gap/overlap at {expected}: "
                    f"next instruction starts at {instruction.position}"
                )
            expected += instruction.size
        if expected != self.target_length:
            raise ValueError(
                f"window {self.index} instructions cover {expected} bytes, "
                f"not {self.target_length}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "target_offset": self.target_offset,
            "target_length": self.target_length,
            "source_used": self.source_used,
            "source_position": self.source_position,
            "source_length": self.source_length,
            "instructions": [instruction.to_dict() for instruction in self.instructions],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WindowTrace:
        return cls(
            index=int(value["index"]),
            target_offset=int(value["target_offset"]),
            target_length=int(value["target_length"]),
            source_used=bool(value["source_used"]),
            source_position=int(value["source_position"]),
            source_length=int(value["source_length"]),
            instructions=tuple(Instruction.from_dict(item) for item in value["instructions"]),
        )


@dataclass(frozen=True)
class CodeEntry:
    inst1: int
    size1: int
    mode1: int
    inst2: int = NOOP
    size2: int = 0
    mode2: int = 0

    def __post_init__(self) -> None:
        for field in (self.inst1, self.size1, self.mode1, self.inst2, self.size2, self.mode2):
            if not 0 <= field <= 255:
                raise ValueError(f"code-table byte out of range: {field}")
        if self.inst1 not in (ADD, RUN, COPY):
            raise ValueError("the first half of an entry must be ADD, RUN, or COPY")
        if self.inst2 not in (NOOP, ADD, RUN, COPY):
            raise ValueError("invalid second instruction")
        if self.inst1 != COPY and self.mode1 != 0:
            raise ValueError("non-COPY first instruction has a nonzero mode")
        if self.inst2 != COPY and self.mode2 != 0:
            raise ValueError("non-COPY second instruction has a nonzero mode")
        if self.inst2 == NOOP and (self.size2 != 0 or self.mode2 != 0):
            raise ValueError("NOOP must have zero size and mode")

    @property
    def width(self) -> int:
        return 1 if self.inst2 == NOOP else 2

    def exact_pattern(self) -> Pattern | None:
        if self.size1 == 0 or (self.inst2 != NOOP and self.size2 == 0):
            return None
        atoms = [Atom(self.inst1, self.size1, self.mode1)]
        if self.inst2 != NOOP:
            atoms.append(Atom(self.inst2, self.size2, self.mode2))
        return Pattern(tuple(atoms))

    @classmethod
    def from_pattern(cls, pattern: Pattern) -> CodeEntry:
        first = pattern.atoms[0]
        if pattern.width == 1:
            return cls(first.type_id, first.size, first.mode)
        second = pattern.atoms[1]
        return cls(
            first.type_id,
            first.size,
            first.mode,
            second.type_id,
            second.size,
            second.mode,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "inst1": self.inst1,
            "size1": self.size1,
            "mode1": self.mode1,
            "inst2": self.inst2,
            "size2": self.size2,
            "mode2": self.mode2,
        }


def observed_patterns(windows: Iterable[WindowTrace]) -> tuple[Pattern, ...]:
    patterns: set[Pattern] = set()
    for window in windows:
        instructions = window.instructions
        for index, instruction in enumerate(instructions):
            if instruction.size <= 255:
                patterns.add(Pattern((instruction.atom,)))
            if index + 1 < len(instructions):
                second = instructions[index + 1]
                if instruction.size <= 255 and second.size <= 255:
                    patterns.add(Pattern((instruction.atom, second.atom)))
    return tuple(sorted(patterns))
