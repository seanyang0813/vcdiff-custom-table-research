from __future__ import annotations

import hashlib
import itertools

import numpy as np
from scipy.optimize import Bounds, LinearConstraint
from scipy.sparse import csr_matrix

import vcdiff_opt.optimizer as optimizer_module
from benchmark.integer_dual_adapter import (
    IntegerDualAdapter,
    IntegerDualReplayAdapter,
    RationalDualBoundReplayAdapter,
)
from benchmark_android.finalize_integer_dual_pair import (
    capture_fixed_q_model_fingerprint,
)
from vcdiff_opt.codec import build_custom_table, encode_file, encode_file_header
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.default_table import (
    DEFAULT_TABLE,
    DEFAULT_TABLE_BYTES,
    PAIR_BANK_CAPACITY,
    PAIR_BANK_START,
)
from vcdiff_opt.model import ADD, COPY, Atom, Instruction, Pattern, WindowTrace
from vcdiff_opt.optimizer import solve_global_selection, solve_selection
from vcdiff_opt.parser import optimal_parse
from vcdiff_opt.varint import decode_varint, encode_varint


def test_activation_links_preserve_binary_selection_feasible_set() -> None:
    """The exact-SCIP activation strengthening is integer-redundant."""
    for count in range(1, 8):
        for selected in (0, 1):
            for occurrences in itertools.product((0, 1), repeat=count):
                original = sum(occurrences) <= count * selected
                strengthened = original and all(
                    occurrence <= selected for occurrence in occurrences
                )
                assert original == strengthened


def test_varint_round_trip_and_known_encodings() -> None:
    known = {
        0: "00",
        127: "7f",
        128: "8100",
        255: "817f",
        256: "8200",
        1536: "8c00",
    }
    for value, encoded_hex in known.items():
        encoded = encode_varint(value)
        assert encoded.hex() == encoded_hex
        assert decode_varint(encoded) == (value, len(encoded))


def test_rfc_default_table_fingerprint() -> None:
    assert len(DEFAULT_TABLE) == 256
    assert len(DEFAULT_TABLE_BYTES) == 1536
    assert (
        hashlib.sha256(DEFAULT_TABLE_BYTES).hexdigest()
        == "4c2cf2bfe3314edab8dec67ed6d735e591c166f190ae4f9ab7ca7fdf3f096c05"
    )
    assert DEFAULT_TABLE[0].inst1 == 2  # RUN, explicit size
    assert DEFAULT_TABLE[1].inst1 == ADD and DEFAULT_TABLE[1].size1 == 0
    assert DEFAULT_TABLE[19].inst1 == 3 and DEFAULT_TABLE[19].mode1 == 0
    assert DEFAULT_TABLE[255].width == 2
    pair_patterns = [
        entry.exact_pattern() for entry in DEFAULT_TABLE[PAIR_BANK_START:]
    ]
    assert len(pair_patterns) == PAIR_BANK_CAPACITY
    assert None not in pair_patterns
    assert len(set(pair_patterns)) == PAIR_BANK_CAPACITY


def _add_trace(count: int = 4, size: int = 18) -> WindowTrace:
    return WindowTrace(
        index=0,
        target_offset=0,
        target_length=count * size,
        source_used=False,
        source_position=0,
        source_length=0,
        instructions=tuple(
            Instruction(position=index * size, type_id=ADD, size=size)
            for index in range(count)
        ),
    )


def test_milp_matches_bruteforce_and_custom_patch_round_trips() -> None:
    window = _add_trace()
    single = Pattern((window.instructions[0].atom,))
    pair = Pattern((window.instructions[0].atom, window.instructions[1].atom))
    candidates = (single, pair)

    brute = []
    for pattern in candidates:
        table = build_custom_table((pattern,), 1)
        brute.append((optimal_parse(window.instructions, table).byte_cost, pattern))
    brute_cost, brute_pattern = min(brute)

    result = solve_selection((window,), 1, candidates=candidates)
    assert result.instruction_bytes == result.solver_dual_bound == brute_cost
    assert result.solver_gap == 0.0
    assert result.selected == (brute_pattern,)

    target = bytes(range(window.target_length))
    table = build_custom_table(result.selected, 1)
    encoding = encode_file(
        (window,), b"", target, table=table, physical_slots=1
    )
    assert decode_file(encoding.encoded, b"") == target
    assert encoding.windows[0].instruction_length == brute_cost


def test_integer_dual_adapter_writes_and_replays_exact_proof(tmp_path) -> None:
    window = _add_trace()
    single = Pattern((window.instructions[0].atom,))
    pair = Pattern((window.instructions[0].atom, window.instructions[1].atom))
    candidates = (single, pair)
    original = optimizer_module.milp
    constructor = IntegerDualAdapter(proof_directory=tmp_path)
    optimizer_module.milp = constructor
    try:
        constructed = optimizer_module.solve_selection(
            (window,), 1, candidates=candidates
        )
    finally:
        optimizer_module.milp = original
    assert constructed.instruction_bytes == constructor.calls[0].exact_dual_bound

    replay = IntegerDualReplayAdapter(tmp_path)
    optimizer_module.milp = replay
    try:
        replayed = optimizer_module.solve_selection(
            (window,), 1, candidates=candidates
        )
    finally:
        optimizer_module.milp = original
    assert replayed == constructed
    assert replay.calls[0].exact_objective == constructed.instruction_bytes

    bound_replay = RationalDualBoundReplayAdapter(tmp_path)
    optimizer_module.milp = bound_replay
    try:
        try:
            optimizer_module.solve_selection((window,), 1, candidates=candidates)
        except RuntimeError as error:
            assert "replayed_exact_rational_bound_only" in str(error)
        else:
            raise AssertionError("bound-only replay unexpectedly returned a witness")
    finally:
        optimizer_module.milp = original
    assert (
        bound_replay.calls[0].integer_lattice_lower_bound
        == constructed.instruction_bytes
    )


def test_fixed_q_model_fingerprint_capture_is_deterministic() -> None:
    windows = (_add_trace(count=5),)
    first = capture_fixed_q_model_fingerprint(windows, 1)
    second = capture_fixed_q_model_fingerprint(windows, 1)
    assert first == second
    assert len(first) == 64


def test_integer_dual_adapter_replays_fractional_bound_ceiling(tmp_path) -> None:
    # The strengthened root LP has x0=x1=y=1/2 and objective 1/2, while the
    # binary-selection problem requires y=1.  This exercises a denominator-2
    # dual and the integer-objective ceiling rule independently of VCDIFF.
    objective = np.asarray([0, 0, 1], dtype=float)
    integrality = np.asarray([0, 0, 1], dtype=np.uint8)
    bounds = Bounds(np.zeros(3), np.ones(3))
    constraints = LinearConstraint(
        csr_matrix(np.asarray([[1, 1, 0], [1, 1, -2]], dtype=float)),
        np.asarray([1, -np.inf]),
        np.asarray([1, 0]),
    )
    constructor = IntegerDualAdapter(proof_directory=tmp_path)
    result = constructor(
        c=objective,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
    )
    assert result.success
    assert constructor.calls[0].exact_dual_numerator == 1
    assert constructor.calls[0].exact_dual_denominator == 2
    assert constructor.calls[0].exact_objective == 1

    replay = IntegerDualReplayAdapter(tmp_path)
    replayed = replay(
        c=objective,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
    )
    assert replayed.success
    assert replay.calls[0].exact_objective == 1

    reuse_directory = tmp_path / "reuse"
    bound_constructor = IntegerDualAdapter(
        proof_directory=reuse_directory,
        bound_only=True,
    )
    bound_result = bound_constructor(
        c=objective,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
    )
    assert not bound_result.success
    witness_constructor = IntegerDualAdapter(
        proof_directory=reuse_directory,
        replay_bound_directory=reuse_directory,
        candidate_presolve_attempts=(True,),
    )
    witness_result = witness_constructor(
        c=objective,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
    )
    assert witness_result.success
    assert witness_constructor.bound_calls[0].lp_elapsed_seconds == 0.0
    assert witness_constructor.calls[0].exact_objective == 1


def test_default_table_patch_round_trips() -> None:
    window = _add_trace(count=3, size=18)
    target = bytes(range(window.target_length))
    encoding = encode_file((window,), b"", target)
    assert decode_file(encoding.encoded, b"") == target


def test_global_milp_matches_exhaustive_small_family() -> None:
    window = _add_trace(count=5, size=18)
    target = bytes(range(window.target_length))
    single = Pattern((window.instructions[0].atom,))
    pair = Pattern((window.instructions[0].atom, window.instructions[1].atom))
    candidates = (single, pair)
    probe = Pattern((Atom(ADD, 255),))
    header_lengths = [len(encode_file_header()[0])]
    for q in (1, 2):
        header_lengths.append(len(encode_file_header(build_custom_table((probe,), q), q)[0]))

    default_encoding = encode_file((window,), b"", target)
    result = solve_global_selection(
        window,
        2,
        file_header_lengths=header_lengths,
        data_bytes=default_encoding.windows[0].data_length,
        address_bytes=default_encoding.windows[0].address_length,
        candidates=candidates,
    )

    exhaustive = [(len(default_encoding.encoded), 0, tuple())]
    for q in (1, 2):
        for count in range(1, min(q, len(candidates)) + 1):
            for selected in itertools.combinations(candidates, count):
                table = build_custom_table(selected, q)
                encoded = encode_file(
                    (window,), b"", target, table=table, physical_slots=q
                )
                exhaustive.append((len(encoded.encoded), q, selected))
    assert result.patch_bytes == result.patch_dual_bound == min(row[0] for row in exhaustive)
    assert result.solver_gap == 0.0

    if result.physical_slots == 0:
        attained = default_encoding
    else:
        attained = encode_file(
            (window,),
            b"",
            target,
            table=build_custom_table(result.selected, result.physical_slots),
            physical_slots=result.physical_slots,
        )
    assert len(attained.encoded) == result.patch_bytes
    assert decode_file(attained.encoded, b"") == target


def test_global_milp_accounts_for_overwritten_default_pair() -> None:
    source = b"abcd"
    target = bytearray()
    instructions = []
    for repetition in range(100):
        for marker in (17, 33):
            position = len(target)
            payload = bytes(((repetition + marker + i) & 0xFF) for i in range(18))
            target.extend(payload)
            instructions.append(Instruction(position=position, type_id=ADD, size=18))
        position = len(target)
        target.append(repetition & 0xFF)
        instructions.append(Instruction(position=position, type_id=ADD, size=1))
        position = len(target)
        target.extend(source)
        instructions.append(
            Instruction(
                position=position,
                type_id=COPY,
                size=4,
                mode=0,
                address=0,
                source_copy=True,
            )
        )
    window = WindowTrace(
        index=0,
        target_offset=0,
        target_length=len(target),
        source_used=True,
        source_position=0,
        source_length=len(source),
        instructions=tuple(instructions),
    )
    new_pair = Pattern((instructions[0].atom, instructions[1].atom))
    overwritten_default_pair = Pattern((instructions[2].atom, instructions[3].atom))
    candidates = (new_pair, overwritten_default_pair)
    probe = Pattern((Atom(ADD, 255),))
    header_lengths = [len(encode_file_header()[0])]
    for q in (1, 2):
        header_lengths.append(len(encode_file_header(build_custom_table((probe,), q), q)[0]))

    default_encoding = encode_file((window,), source, bytes(target))
    result = solve_global_selection(
        window,
        2,
        file_header_lengths=header_lengths,
        data_bytes=default_encoding.windows[0].data_length,
        address_bytes=default_encoding.windows[0].address_length,
        candidates=candidates,
    )
    exhaustive = [len(default_encoding.encoded)]
    for q in (1, 2):
        for count in range(1, min(q, len(candidates)) + 1):
            for selected in itertools.combinations(candidates, count):
                table = build_custom_table(selected, q)
                if table == DEFAULT_TABLE:
                    continue
                exhaustive.append(
                    len(
                        encode_file(
                            (window,),
                            source,
                            bytes(target),
                            table=table,
                            physical_slots=q,
                        ).encoded
                    )
                )
    assert result.patch_bytes == result.patch_dual_bound == min(exhaustive)
    assert result.physical_slots == 2
    assert set(result.selected) == set(candidates)


def test_global_optimizer_returns_default_when_no_pattern_can_improve() -> None:
    window = _add_trace(count=1, size=1)
    target = b"x"
    default_encoding = encode_file((window,), b"", target)
    probe = Pattern((Atom(ADD, 255),))
    header_lengths = [
        len(encode_file_header()[0]),
        len(encode_file_header(build_custom_table((probe,), 1), 1)[0]),
    ]
    result = solve_global_selection(
        window,
        1,
        file_header_lengths=header_lengths,
        data_bytes=default_encoding.windows[0].data_length,
        address_bytes=default_encoding.windows[0].address_length,
    )
    assert result.physical_slots == 0
    assert result.selected == tuple()
    assert result.patch_bytes == result.patch_dual_bound == len(default_encoding.encoded)
