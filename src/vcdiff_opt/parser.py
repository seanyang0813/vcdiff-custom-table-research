from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Sequence

from .model import NOOP, Atom, CodeEntry, Instruction
from .varint import varint_size


@dataclass(frozen=True)
class ParseToken:
    start: int
    width: int
    opcode: int
    byte_cost: int

    def to_dict(self) -> dict[str, int]:
        return {
            "start": self.start,
            "width": self.width,
            "opcode": self.opcode,
            "byte_cost": self.byte_cost,
        }


@dataclass(frozen=True)
class ParseResult:
    byte_cost: int
    tokens: tuple[ParseToken, ...]


def _half_cost(inst: int, size: int, mode: int, atom: Atom) -> int | None:
    if inst != atom.type_id or mode != atom.mode:
        return None
    if size == atom.size:
        return 0
    if size == 0:
        return varint_size(atom.size)
    return None


def entry_cost(entry: CodeEntry, atoms: Sequence[Atom]) -> int | None:
    if len(atoms) != entry.width:
        return None
    first = _half_cost(entry.inst1, entry.size1, entry.mode1, atoms[0])
    if first is None:
        return None
    if entry.inst2 == NOOP:
        return 1 + first
    second = _half_cost(entry.inst2, entry.size2, entry.mode2, atoms[1])
    if second is None:
        return None
    return 1 + first + second


def best_entry(
    table: Sequence[CodeEntry], atoms: Sequence[Atom]
) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for opcode, entry in enumerate(table):
        cost = entry_cost(entry, atoms)
        if cost is None:
            continue
        candidate = (cost, opcode)
        if best is None or candidate < best:
            best = candidate
    return best


def optimal_parse(
    instructions: Sequence[Instruction], table: Sequence[CodeEntry]
) -> ParseResult:
    count = len(instructions)
    costs = [inf] * (count + 1)
    choices: list[ParseToken | None] = [None] * count
    costs[count] = 0

    for start in range(count - 1, -1, -1):
        options: list[tuple[float, int, int, ParseToken]] = []
        for width in (1, 2):
            if start + width > count:
                continue
            atoms = tuple(
                instructions[index].atom for index in range(start, start + width)
            )
            match = best_entry(table, atoms)
            if match is None:
                continue
            token_cost, opcode = match
            total = token_cost + costs[start + width]
            token = ParseToken(start, width, opcode, token_cost)
            # Prefer a double instruction, then the smaller opcode, on ties.
            options.append((total, -width, opcode, token))
        if not options:
            raise ValueError(f"code table cannot encode instruction {start}")
        total, _, _, choice = min(options)
        costs[start] = total
        choices[start] = choice

    tokens: list[ParseToken] = []
    position = 0
    while position < count:
        token = choices[position]
        if token is None:
            raise AssertionError("missing dynamic-programming choice")
        tokens.append(token)
        position += token.width
    return ParseResult(int(costs[0]), tuple(tokens))


def encode_instruction_section(
    instructions: Sequence[Instruction],
    table: Sequence[CodeEntry],
    parse: ParseResult,
) -> bytes:
    from .varint import encode_varint

    output = bytearray()
    expected_start = 0
    for token in parse.tokens:
        if token.start != expected_start:
            raise ValueError("parse tokens are not contiguous")
        entry = table[token.opcode]
        atoms = tuple(
            instructions[index].atom
            for index in range(token.start, token.start + token.width)
        )
        actual_cost = entry_cost(entry, atoms)
        if actual_cost != token.byte_cost:
            raise ValueError("parse token does not match its table entry")
        output.append(token.opcode)
        if entry.size1 == 0:
            output.extend(encode_varint(atoms[0].size))
        if entry.inst2 != NOOP and entry.size2 == 0:
            output.extend(encode_varint(atoms[1].size))
        expected_start += token.width
    if expected_start != len(instructions):
        raise ValueError("parse does not cover the instruction sequence")
    if len(output) != parse.byte_cost:
        raise AssertionError("instruction-section byte count drift")
    return bytes(output)

