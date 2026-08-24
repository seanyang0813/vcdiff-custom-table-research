from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .default_table import DEFAULT_TABLE, PAIR_BANK_CAPACITY, PAIR_BANK_START
from .model import CodeEntry, Pattern, WindowTrace, observed_patterns
from .parser import best_entry, optimal_parse
from .varint import varint_size


@dataclass(frozen=True)
class ModelEdge:
    window: int
    start: int
    width: int
    byte_cost: int
    pattern: Pattern | None


@dataclass(frozen=True)
class SelectionResult:
    physical_slots: int
    selected: tuple[Pattern, ...]
    instruction_bytes: int
    solver_dual_bound: int
    solver_gap: float
    solver_nodes: int
    model_variables: int
    model_constraints: int
    candidate_count: int
    observed_candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "physical_slots": self.physical_slots,
            "selected_patterns": [pattern.to_dict() for pattern in self.selected],
            "instruction_bytes": self.instruction_bytes,
            "solver_dual_bound": self.solver_dual_bound,
            "solver_gap": self.solver_gap,
            "solver_nodes": self.solver_nodes,
            "model_variables": self.model_variables,
            "model_constraints": self.model_constraints,
            "candidate_count": self.candidate_count,
            "observed_candidate_count": self.observed_candidate_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SelectionResult:
        return cls(
            physical_slots=int(value["physical_slots"]),
            selected=tuple(
                Pattern.from_dict(pattern) for pattern in value["selected_patterns"]
            ),
            instruction_bytes=int(value["instruction_bytes"]),
            solver_dual_bound=int(value["solver_dual_bound"]),
            solver_gap=float(value["solver_gap"]),
            solver_nodes=int(value["solver_nodes"]),
            model_variables=int(value["model_variables"]),
            model_constraints=int(value["model_constraints"]),
            candidate_count=int(value["candidate_count"]),
            observed_candidate_count=int(value["observed_candidate_count"]),
        )


@dataclass(frozen=True)
class GlobalSelectionResult:
    max_physical_slots: int
    physical_slots: int
    selected: tuple[Pattern, ...]
    instruction_bytes: int
    file_header_bytes: int
    instruction_length_varint_bytes: int
    delta_length_varint_bytes: int
    variable_patch_bytes: int
    constant_patch_bytes: int
    patch_bytes: int
    solver_dual_bound: int
    patch_dual_bound: int
    solver_gap: float
    solver_nodes: int
    model_variables: int
    model_constraints: int
    candidate_count: int
    observed_candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "max_physical_slots": self.max_physical_slots,
            "physical_slots": self.physical_slots,
            "selected_patterns": [pattern.to_dict() for pattern in self.selected],
            "instruction_bytes": self.instruction_bytes,
            "file_header_bytes": self.file_header_bytes,
            "instruction_length_varint_bytes": self.instruction_length_varint_bytes,
            "delta_length_varint_bytes": self.delta_length_varint_bytes,
            "variable_patch_bytes": self.variable_patch_bytes,
            "constant_patch_bytes": self.constant_patch_bytes,
            "patch_bytes": self.patch_bytes,
            "solver_dual_bound": self.solver_dual_bound,
            "patch_dual_bound": self.patch_dual_bound,
            "solver_gap": self.solver_gap,
            "solver_nodes": self.solver_nodes,
            "model_variables": self.model_variables,
            "model_constraints": self.model_constraints,
            "candidate_count": self.candidate_count,
            "observed_candidate_count": self.observed_candidate_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GlobalSelectionResult:
        return cls(
            max_physical_slots=int(value["max_physical_slots"]),
            physical_slots=int(value["physical_slots"]),
            selected=tuple(
                Pattern.from_dict(pattern) for pattern in value["selected_patterns"]
            ),
            instruction_bytes=int(value["instruction_bytes"]),
            file_header_bytes=int(value["file_header_bytes"]),
            instruction_length_varint_bytes=int(
                value["instruction_length_varint_bytes"]
            ),
            delta_length_varint_bytes=int(value["delta_length_varint_bytes"]),
            variable_patch_bytes=int(value["variable_patch_bytes"]),
            constant_patch_bytes=int(value["constant_patch_bytes"]),
            patch_bytes=int(value["patch_bytes"]),
            solver_dual_bound=int(value["solver_dual_bound"]),
            patch_dual_bound=int(value["patch_dual_bound"]),
            solver_gap=float(value["solver_gap"]),
            solver_nodes=int(value["solver_nodes"]),
            model_variables=int(value["model_variables"]),
            model_constraints=int(value["model_constraints"]),
            candidate_count=int(value["candidate_count"]),
            observed_candidate_count=int(value["observed_candidate_count"]),
        )


def _best_cost(table: Sequence, pattern: Pattern) -> int | None:
    result = best_entry(table, pattern.atoms)
    return None if result is None else result[0]


def solve_selection(
    windows: Sequence[WindowTrace],
    physical_slots: int,
    *,
    candidates: Sequence[Pattern] | None = None,
) -> SelectionResult:
    """Solve the exact restricted table-selection plus pair-parse MILP.

    The table family replaces the prefix of the RFC pair bank beginning at
    opcode 163.  At most ``physical_slots`` distinct observed exact patterns
    are installed; unused physical entries duplicate a selected pattern.
    The remaining table is unchanged.  This makes the canonical table-header
    cost depend only on ``physical_slots`` while the MILP jointly chooses the
    installed patterns and a non-overlapping single/pair parse.
    """
    if not 1 <= physical_slots <= PAIR_BANK_CAPACITY:
        raise ValueError(
            f"physical_slots must be in [1, {PAIR_BANK_CAPACITY}]"
        )
    if not windows:
        raise ValueError("at least one trace window is required")

    observed_candidate_tuple = tuple(
        sorted(set(candidates or observed_patterns(windows)))
    )
    if not observed_candidate_tuple:
        raise ValueError("the trace has no legal implicit-size candidates")
    observed_candidate_set = set(observed_candidate_tuple)

    removed = set(range(PAIR_BANK_START, PAIR_BANK_START + physical_slots))
    base_table = tuple(
        entry for opcode, entry in enumerate(DEFAULT_TABLE) if opcode not in removed
    )

    edges: list[ModelEdge] = []
    covers: dict[tuple[int, int], list[int]] = {}

    def add_edge(edge: ModelEdge) -> None:
        variable = len(edges)
        edges.append(edge)
        for position in range(edge.start, edge.start + edge.width):
            covers.setdefault((edge.window, position), []).append(variable)

    for window_number, window in enumerate(windows):
        instructions = window.instructions
        for start, instruction in enumerate(instructions):
            single = Pattern((instruction.atom,)) if instruction.size <= 255 else None
            single_atoms = (instruction.atom,)
            base_single = best_entry(base_table, single_atoms)
            if base_single is None:
                raise ValueError("preserved generic entries cannot encode the trace")
            add_edge(ModelEdge(window_number, start, 1, base_single[0], None))
            if (
                single is not None
                and single in observed_candidate_set
                and base_single[0] > 1
            ):
                add_edge(ModelEdge(window_number, start, 1, 1, single))

            if start + 1 >= len(instructions):
                continue
            second = instructions[start + 1]
            pair = None
            if instruction.size <= 255 and second.size <= 255:
                pair = Pattern((instruction.atom, second.atom))
            pair_atoms = (instruction.atom, second.atom)
            base_pair = best_entry(base_table, pair_atoms)
            if base_pair is not None:
                add_edge(ModelEdge(window_number, start, 2, base_pair[0], None))
            if (
                pair is not None
                and pair in observed_candidate_set
                and (base_pair is None or base_pair[0] > 1)
            ):
                add_edge(ModelEdge(window_number, start, 2, 1, pair))

    # Observed patterns with no improving occurrence edge are dominated: a
    # physical slot can duplicate any selected entry, so installing one of
    # these patterns can never improve a parse or satisfy a requirement that a
    # duplicate could not.  Removing them is an exact presolve reduction.
    candidate_tuple = tuple(
        sorted({edge.pattern for edge in edges if edge.pattern is not None})
    )
    if not candidate_tuple:
        selected = (observed_candidate_tuple[0],)
        table = list(DEFAULT_TABLE)
        replacement = CodeEntry.from_pattern(selected[0])
        table[
            PAIR_BANK_START : PAIR_BANK_START + physical_slots
        ] = [replacement] * physical_slots
        objective_value = sum(
            optimal_parse(window.instructions, table).byte_cost
            for window in windows
        )
        return SelectionResult(
            physical_slots=physical_slots,
            selected=selected,
            instruction_bytes=objective_value,
            solver_dual_bound=objective_value,
            solver_gap=0.0,
            solver_nodes=0,
            model_variables=0,
            model_constraints=0,
            candidate_count=0,
            observed_candidate_count=len(observed_candidate_tuple),
        )
    candidate_index = {pattern: index for index, pattern in enumerate(candidate_tuple)}
    occurrences_by_pattern: list[list[int]] = [list() for _ in candidate_tuple]
    for variable, edge in enumerate(edges):
        if edge.pattern is not None:
            occurrences_by_pattern[candidate_index[edge.pattern]].append(variable)

    edge_count = len(edges)
    variable_count = edge_count + len(candidate_tuple)
    objective = np.zeros(variable_count, dtype=float)
    for index, edge in enumerate(edges):
        objective[index] = edge.byte_cost

    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    lower: list[float] = []
    upper: list[float] = []

    def add_row(coefficients: Sequence[tuple[int, float]], lb: float, ub: float) -> None:
        row = len(lower)
        for column, value in coefficients:
            rows.append(row)
            columns.append(column)
            values.append(value)
        lower.append(lb)
        upper.append(ub)

    for window_number, window in enumerate(windows):
        for position in range(len(window.instructions)):
            variables = covers.get((window_number, position), [])
            if not variables:
                raise AssertionError("an instruction has no covering parse edge")
            add_row([(variable, 1.0) for variable in variables], 1.0, 1.0)

    for pattern_number, occurrence_variables in enumerate(occurrences_by_pattern):
        selection_variable = edge_count + pattern_number
        coefficients = [(variable, 1.0) for variable in occurrence_variables]
        coefficients.append((selection_variable, -float(len(occurrence_variables))))
        add_row(coefficients, -np.inf, 0.0)

    selection_variables = [
        (edge_count + pattern_number, 1.0)
        for pattern_number in range(len(candidate_tuple))
    ]
    add_row(selection_variables, 1.0, float(physical_slots))

    matrix = coo_matrix(
        (
            np.asarray(values, dtype=float),
            (np.asarray(rows, dtype=np.int32), np.asarray(columns, dtype=np.int32)),
        ),
        shape=(len(lower), variable_count),
    ).tocsc()
    result = milp(
        c=objective,
        # With the table-selection variables fixed, the remaining model is a
        # shortest path on a line (the interval-cover matrix has the
        # consecutive-ones property), so its extreme points are integral.
        # Only the pattern-selection suffix therefore needs integer branching.
        integrality=np.concatenate(
            (
                np.zeros(edge_count, dtype=np.uint8),
                np.ones(len(candidate_tuple), dtype=np.uint8),
            )
        ),
        bounds=Bounds(np.zeros(variable_count), np.ones(variable_count)),
        constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
        options={"mip_rel_gap": 0.0, "presolve": True},
    )
    if not result.success or result.x is None or result.fun is None:
        raise RuntimeError(
            f"MILP did not prove an optimum (status={result.status}): {result.message}"
        )
    objective_value = int(round(float(result.fun)))
    if abs(float(result.fun) - objective_value) > 1e-6:
        raise AssertionError("integral MILP returned a fractional objective")
    dual = int(round(float(result.mip_dual_bound)))
    if dual != objective_value or float(result.mip_gap) > 1e-9:
        raise RuntimeError(
            f"MILP stopped without a zero-gap certificate: primal={objective_value}, "
            f"dual={result.mip_dual_bound}, gap={result.mip_gap}"
        )

    selected = tuple(
        candidate_tuple[index]
        for index in range(len(candidate_tuple))
        if result.x[edge_count + index] > 0.5
    )
    if not 1 <= len(selected) <= physical_slots:
        raise AssertionError("solver selection violates the physical slot bound")

    return SelectionResult(
        physical_slots=physical_slots,
        selected=selected,
        instruction_bytes=objective_value,
        solver_dual_bound=dual,
        solver_gap=float(result.mip_gap),
        solver_nodes=int(result.mip_node_count),
        model_variables=variable_count,
        model_constraints=len(lower),
        candidate_count=len(candidate_tuple),
        observed_candidate_count=len(observed_candidate_tuple),
    )


def _varint_interval(length: int) -> tuple[int, int]:
    if length <= 0:
        raise ValueError("varint length must be positive")
    if length == 1:
        return 0, 127
    return 1 << (7 * (length - 1)), (1 << (7 * length)) - 1


def solve_global_selection(
    window: WindowTrace,
    max_physical_slots: int,
    *,
    file_header_lengths: Sequence[int],
    data_bytes: int,
    address_bytes: int,
    candidates: Sequence[Pattern] | None = None,
) -> GlobalSelectionResult:
    """Jointly optimize slot count, selected patterns, and the pair parse.

    Unlike ``solve_selection``, this model contains binary choices for every
    physical slot count from zero through ``max_physical_slots``.  It charges
    the exact canonical file-header/table-delta length, conditionally removes
    the overwritten RFC pair opcodes, and models both instruction-length and
    delta-length varint step costs.  The result is therefore a lower bound and
    matching construction for total patch bytes in the one-window restricted
    family, up to constants shared by every choice.
    """
    if not 1 <= max_physical_slots <= PAIR_BANK_CAPACITY:
        raise ValueError(
            f"max_physical_slots must be in [1, {PAIR_BANK_CAPACITY}]"
        )
    if len(file_header_lengths) != max_physical_slots + 1:
        raise ValueError("file_header_lengths must contain q=0 through q=max")
    if min(file_header_lengths) <= 0 or data_bytes < 0 or address_bytes < 0:
        raise ValueError("invalid byte-count input")

    observed_candidate_tuple = tuple(
        sorted(set(candidates or observed_patterns((window,))))
    )
    observed_candidate_set = set(observed_candidate_tuple)
    delta_constant = (
        varint_size(window.target_length)
        + 1
        + varint_size(data_bytes)
        + varint_size(address_bytes)
        + data_bytes
        + address_bytes
    )
    window_prefix_bytes = 1
    if window.source_used:
        window_prefix_bytes += varint_size(window.source_length)
        window_prefix_bytes += varint_size(window.source_position)
    constant_patch_bytes = window_prefix_bytes + delta_constant
    edges: list[ModelEdge] = []
    covers: dict[int, list[int]] = {}
    conditional_default: dict[int, list[int]] = {}

    def add_edge(edge: ModelEdge, lost_at: int | None = None) -> None:
        variable = len(edges)
        edges.append(edge)
        for position in range(edge.start, edge.start + edge.width):
            covers.setdefault(position, []).append(variable)
        if lost_at is not None and lost_at <= max_physical_slots:
            conditional_default.setdefault(lost_at, []).append(variable)

    instructions = window.instructions
    for start, instruction in enumerate(instructions):
        single_atoms = (instruction.atom,)
        base_single = best_entry(DEFAULT_TABLE, single_atoms)
        if base_single is None:
            raise ValueError("RFC generic singles cannot encode the trace")
        add_edge(ModelEdge(0, start, 1, base_single[0], None))
        if instruction.size <= 255:
            single = Pattern(single_atoms)
            if single in observed_candidate_set and base_single[0] > 1:
                add_edge(ModelEdge(0, start, 1, 1, single))

        if start + 1 >= len(instructions):
            continue
        second = instructions[start + 1]
        pair_atoms = (instruction.atom, second.atom)
        base_pair = best_entry(DEFAULT_TABLE, pair_atoms)
        lost_at: int | None = None
        if base_pair is not None:
            _, opcode = base_pair
            if opcode >= PAIR_BANK_START:
                lost_at = opcode - PAIR_BANK_START + 1
            add_edge(ModelEdge(0, start, 2, base_pair[0], None), lost_at)
        if instruction.size <= 255 and second.size <= 255:
            pair = Pattern(pair_atoms)
            default_always_available = (
                base_pair is not None
                and base_pair[0] == 1
                and (lost_at is None or lost_at > max_physical_slots)
            )
            if pair in observed_candidate_set and not default_always_available:
                add_edge(ModelEdge(0, start, 2, 1, pair))

    candidate_tuple = tuple(
        sorted({edge.pattern for edge in edges if edge.pattern is not None})
    )
    if not candidate_tuple:
        instruction_bytes = optimal_parse(
            window.instructions, DEFAULT_TABLE
        ).byte_cost
        instruction_varint_bytes = varint_size(instruction_bytes)
        delta_bytes = delta_constant + instruction_varint_bytes + instruction_bytes
        delta_varint_bytes = varint_size(delta_bytes)
        variable_patch_bytes = (
            file_header_lengths[0]
            + instruction_bytes
            + instruction_varint_bytes
            + delta_varint_bytes
        )
        patch_bytes = variable_patch_bytes + constant_patch_bytes
        return GlobalSelectionResult(
            max_physical_slots=max_physical_slots,
            physical_slots=0,
            selected=tuple(),
            instruction_bytes=instruction_bytes,
            file_header_bytes=int(file_header_lengths[0]),
            instruction_length_varint_bytes=instruction_varint_bytes,
            delta_length_varint_bytes=delta_varint_bytes,
            variable_patch_bytes=variable_patch_bytes,
            constant_patch_bytes=constant_patch_bytes,
            patch_bytes=patch_bytes,
            solver_dual_bound=variable_patch_bytes,
            patch_dual_bound=patch_bytes,
            solver_gap=0.0,
            solver_nodes=0,
            model_variables=0,
            model_constraints=0,
            candidate_count=0,
            observed_candidate_count=len(observed_candidate_tuple),
        )
    candidate_index = {pattern: index for index, pattern in enumerate(candidate_tuple)}
    occurrences_by_pattern: list[list[int]] = [list() for _ in candidate_tuple]
    for variable, edge in enumerate(edges):
        if edge.pattern is not None:
            occurrences_by_pattern[candidate_index[edge.pattern]].append(variable)

    edge_count = len(edges)
    selection_offset = edge_count
    slot_offset = selection_offset + len(candidate_tuple)

    min_instruction_bytes = (len(instructions) + 1) // 2
    max_instruction_bytes = sum(
        best_entry(DEFAULT_TABLE, (instruction.atom,))[0]
        for instruction in instructions
    )
    piecewise_states: list[tuple[int, int, int, int]] = []
    max_length = max(1, (max_instruction_bytes.bit_length() + 6) // 7)
    max_delta = delta_constant + max_instruction_bytes + max_length
    max_delta_length = max(1, (max_delta.bit_length() + 6) // 7)
    for instruction_varint_bytes in range(1, max_length + 1):
        inst_low, inst_high = _varint_interval(instruction_varint_bytes)
        for delta_varint_bytes in range(1, max_delta_length + 1):
            delta_low, delta_high = _varint_interval(delta_varint_bytes)
            low = max(
                min_instruction_bytes,
                inst_low,
                delta_low - delta_constant - instruction_varint_bytes,
            )
            high = min(
                max_instruction_bytes,
                inst_high,
                delta_high - delta_constant - instruction_varint_bytes,
            )
            if low <= high:
                piecewise_states.append(
                    (instruction_varint_bytes, delta_varint_bytes, low, high)
                )
    if not piecewise_states:
        raise AssertionError("no feasible varint-length state")
    state_offset = slot_offset + max_physical_slots + 1
    variable_count = state_offset + len(piecewise_states)

    objective = np.zeros(variable_count, dtype=float)
    for index, edge in enumerate(edges):
        objective[index] = edge.byte_cost
    for q, header_length in enumerate(file_header_lengths):
        objective[slot_offset + q] = header_length
    for state, (instruction_length, delta_length, _, _) in enumerate(piecewise_states):
        objective[state_offset + state] = instruction_length + delta_length

    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    lower: list[float] = []
    upper: list[float] = []

    def add_row(coefficients: Sequence[tuple[int, float]], lb: float, ub: float) -> None:
        row = len(lower)
        for column, value in coefficients:
            rows.append(row)
            columns.append(column)
            values.append(value)
        lower.append(lb)
        upper.append(ub)

    for position in range(len(instructions)):
        add_row([(variable, 1.0) for variable in covers[position]], 1.0, 1.0)

    for pattern_number, occurrence_variables in enumerate(occurrences_by_pattern):
        coefficients = [(variable, 1.0) for variable in occurrence_variables]
        coefficients.append(
            (selection_offset + pattern_number, -float(len(occurrence_variables)))
        )
        add_row(coefficients, -np.inf, 0.0)

    for lost_at, occurrence_variables in conditional_default.items():
        coefficients = [(variable, 1.0) for variable in occurrence_variables]
        multiplier = float(len(occurrence_variables))
        coefficients.extend(
            (slot_offset + q, -multiplier) for q in range(0, lost_at)
        )
        add_row(coefficients, -np.inf, 0.0)

    slot_variables = [
        (slot_offset + q, 1.0) for q in range(max_physical_slots + 1)
    ]
    add_row(slot_variables, 1.0, 1.0)
    selection_variables = [
        (selection_offset + index, 1.0) for index in range(len(candidate_tuple))
    ]
    capacity = selection_variables + [
        (slot_offset + q, -float(q)) for q in range(max_physical_slots + 1)
    ]
    add_row(capacity, -np.inf, 0.0)
    nonempty = selection_variables + [
        (slot_offset + q, -1.0) for q in range(1, max_physical_slots + 1)
    ]
    add_row(nonempty, 0.0, np.inf)

    state_variables = [
        (state_offset + index, 1.0) for index in range(len(piecewise_states))
    ]
    add_row(state_variables, 1.0, 1.0)
    instruction_expression = [
        (index, float(edge.byte_cost)) for index, edge in enumerate(edges)
    ]
    lower_state = instruction_expression + [
        (state_offset + index, -float(state[2]))
        for index, state in enumerate(piecewise_states)
    ]
    upper_state = instruction_expression + [
        (state_offset + index, -float(state[3]))
        for index, state in enumerate(piecewise_states)
    ]
    add_row(lower_state, 0.0, np.inf)
    add_row(upper_state, -np.inf, 0.0)

    matrix = coo_matrix(
        (
            np.asarray(values, dtype=float),
            (np.asarray(rows, dtype=np.int32), np.asarray(columns, dtype=np.int32)),
        ),
        shape=(len(lower), variable_count),
    ).tocsc()
    integrality = np.zeros(variable_count, dtype=np.uint8)
    integrality[selection_offset:] = 1
    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(np.zeros(variable_count), np.ones(variable_count)),
        constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
        options={"mip_rel_gap": 0.0, "presolve": True},
    )
    if not result.success or result.x is None or result.fun is None:
        raise RuntimeError(
            f"global MILP did not prove an optimum (status={result.status}): {result.message}"
        )
    primal = int(round(float(result.fun)))
    dual = int(round(float(result.mip_dual_bound)))
    if primal != dual or float(result.mip_gap) > 1e-9:
        raise RuntimeError(
            f"global MILP has a nonzero gap: primal={primal}, dual={result.mip_dual_bound}"
        )
    physical_slots = max(
        range(max_physical_slots + 1),
        key=lambda q: result.x[slot_offset + q],
    )
    selected = tuple(
        candidate_tuple[index]
        for index in range(len(candidate_tuple))
        if result.x[selection_offset + index] > 0.5
    )
    state_number = max(
        range(len(piecewise_states)),
        key=lambda index: result.x[state_offset + index],
    )
    instruction_varint_bytes, delta_varint_bytes, _, _ = piecewise_states[state_number]
    instruction_bytes_float = sum(
        edge.byte_cost * result.x[index] for index, edge in enumerate(edges)
    )
    instruction_bytes = int(round(float(instruction_bytes_float)))
    expected_variable = (
        instruction_bytes
        + file_header_lengths[physical_slots]
        + instruction_varint_bytes
        + delta_varint_bytes
    )
    if expected_variable != primal:
        raise AssertionError("global objective decomposition mismatch")
    if physical_slots == 0 and selected:
        raise AssertionError("default-table choice selected custom patterns")
    if physical_slots > 0 and not 1 <= len(selected) <= physical_slots:
        raise AssertionError("global selection violates slot capacity")
    attained_table = list(DEFAULT_TABLE)
    if physical_slots > 0:
        installed = [CodeEntry.from_pattern(pattern) for pattern in selected]
        installed.extend([installed[0]] * (physical_slots - len(installed)))
        attained_table[
            PAIR_BANK_START : PAIR_BANK_START + physical_slots
        ] = installed
    attained_instruction_bytes = optimal_parse(
        window.instructions, attained_table
    ).byte_cost
    # The varint-regime rows can destroy total unimodularity of the relaxed
    # parse subproblem.  Its optimum is still a valid lower bound.  Return a
    # certificate only when the selected table's independent integral DP
    # attains that bound; otherwise this formulation must be strengthened.
    if attained_instruction_bytes != instruction_bytes:
        raise RuntimeError(
            "global parse relaxation was not attained by the selected table: "
            f"lower_bound={instruction_bytes}, dp={attained_instruction_bytes}"
        )
    return GlobalSelectionResult(
        max_physical_slots=max_physical_slots,
        physical_slots=physical_slots,
        selected=selected,
        instruction_bytes=instruction_bytes,
        file_header_bytes=int(file_header_lengths[physical_slots]),
        instruction_length_varint_bytes=instruction_varint_bytes,
        delta_length_varint_bytes=delta_varint_bytes,
        variable_patch_bytes=primal,
        constant_patch_bytes=constant_patch_bytes,
        patch_bytes=primal + constant_patch_bytes,
        solver_dual_bound=dual,
        patch_dual_bound=dual + constant_patch_bytes,
        solver_gap=float(result.mip_gap),
        solver_nodes=int(result.mip_node_count),
        model_variables=variable_count,
        model_constraints=len(lower),
        candidate_count=len(candidate_tuple),
        observed_candidate_count=len(observed_candidate_tuple),
    )
