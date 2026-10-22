import cmath
from dataclasses import dataclass
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qls import Frame, write_qls


INPUT_BITS = 6
SUM_BITS = 6
N_QUBITS = 2 * INPUT_BITS + SUM_BITS
FRAMES_PER_TURN = 60
FRAME_MS = 50  # Animation metadata; the viewer selects its own playback rate.


@dataclass(frozen=True)
class Gate:
    operation: str
    qubits: tuple
    angle: float = 0.0


def qft_gates(inverse=False, sum_bits=SUM_BITS):
    """Positive-exponent QFT on the low sum_bits qubits, including swaps."""
    gates = []
    for target in reversed(range(sum_bits)):
        gates.append(Gate("H", (target,)))
        for control in range(target):
            angle = math.tau / 2 ** (target - control + 1)
            gates.append(Gate("CP", (control, target), angle))
    for low in range(sum_bits // 2):
        gates.append(Gate("SWAP", (low, sum_bits - 1 - low)))
    if inverse:
        return [Gate(g.operation, g.qubits, -g.angle) for g in reversed(gates)]
    return gates


def addition_gates(input_qubits, sum_bits=SUM_BITS):
    """Multiply Fourier mode k by exp(+2πi * input * k/2^sum_bits).

    Input bit i and Fourier bit j contribute angle 2π*2^(i+j)/2^sum_bits.
    Terms with i+j >= sum_bits are whole turns and therefore the identity.
    """
    for bit, control in enumerate(input_qubits):
        for target in range(sum_bits - bit):
            yield Gate("CP", (control, target), math.tau / 2 ** (sum_bits - bit - target))


def circuit(input_bits=INPUT_BITS, sum_bits=SUM_BITS):
    # Each register lists its least significant bit first. In a displayed basis
    # string, the order is |A>|B>|S>, with S occupying the low sum_bits qubits.
    a_qubits = range(sum_bits + input_bits, sum_bits + 2 * input_bits)
    b_qubits = range(sum_bits, sum_bits + input_bits)
    for stage, gates in (
        ("QFT S", qft_gates(sum_bits=sum_bits)),
        ("Add A into S", addition_gates(a_qubits, sum_bits=sum_bits)),
        ("Add B into S", addition_gates(b_qubits, sum_bits=sum_bits)),
        ("Inverse QFT S", qft_gates(inverse=True, sum_bits=sum_bits)),
    ):
        for gate in gates:
            yield stage, gate


def apply_gate(state, gate):
    """Apply one gate in place; q0 is the least significant basis-index bit."""
    if gate.operation == "H":
        mask = 1 << gate.qubits[0]
        scale = 1 / math.sqrt(2)
        for low in range(len(state)):
            if not low & mask:
                high = low | mask
                a, b = state[low], state[high]
                state[low], state[high] = (a + b) * scale, (a - b) * scale
    elif gate.operation == "CP":
        mask = sum(1 << q for q in gate.qubits)
        phase = cmath.exp(1j * gate.angle)
        for index in range(len(state)):
            if index & mask == mask:
                state[index] *= phase
    elif gate.operation == "SWAP":
        first, second = (1 << q for q in gate.qubits)
        for index in range(len(state)):
            if index & first and not index & second:
                other = index ^ first ^ second
                state[index], state[other] = state[other], state[index]
    else:
        raise ValueError(f"Unknown gate: {gate.operation}")


def rotation_steps(angle):
    """At most one sixtieth of a turn per interval, including small rotations."""
    return max(1, math.ceil(abs(angle) / math.tau * FRAMES_PER_TURN))


def animate_gate(state, gate):
    """Yield progress after each update. The preceding frame is the start endpoint.

    For CP gates, evaluate each fractional rotation from the gate's initial
    amplitudes, avoiding accumulated stepping error and amplitude interpolation.
    Hadamards and swaps take one step. This generator mutates state in place.
    """
    if gate.operation != "CP":
        apply_gate(state, gate)
        yield 1, 1
        return
    mask = sum(1 << q for q in gate.qubits)
    initial = [(k, value) for k, value in enumerate(state) if k & mask == mask]
    steps = rotation_steps(gate.angle)
    for step in range(1, steps + 1):
        phase = cmath.exp(1j * gate.angle * step / steps)
        for index, value in initial:
            state[index] = value * phase
        yield step, steps


def addition_history(*, input_bits=INPUT_BITS, sum_bits=SUM_BITS):
    """Stream the entire pure state, including both superposed input registers.

    Inputs start in H^input_bits |0...0> = |+...+>. The final amplitude is
    1/2^input_bits for each |a>|b>|(a+b) mod 2^sum_bits>. All other amplitudes
    vanish, up to roundoff. Each frame owns its amplitude list.
    """
    if any(not isinstance(bits, int) or bits < 1 for bits in (input_bits, sum_bits)):
        raise ValueError("Register widths must be positive integers.")
    n = 2 * input_bits + sum_bits
    if n > 20 or n % 2:
        raise ValueError("The QLS recording needs an even total of at most 20 qubits.")
    state = [0j] * (1 << n)
    # Prepare both Hadamard-transformed inputs directly, without extra frames.
    for inputs in range(1 << (2 * input_bits)):
        state[inputs << sum_bits] = 1 / (1 << input_bits)
    plus = "+" * input_bits
    yield Frame(state.copy(), 0,
                f"Inputs |{plus}>|{plus}>|{'0' * sum_bits}> (A, B, S; "
                f"{input_bits}+{input_bits}+{sum_bits} qubits)")
    frame_number = 0
    for stage, gate in circuit(input_bits, sum_bits):
        qubits = ", ".join(f"q{q}" for q in gate.qubits)
        for step, steps in animate_gate(state, gate):
            frame_number += 1
            title = f"{stage}: {gate.operation}({qubits})"
            if gate.operation == "CP":
                angle = gate.angle * step / steps
                title += f"; angle {angle / math.pi:.6g}π; step {step}/{steps}"
            yield Frame(state.copy(), frame_number * FRAME_MS, title)
    yield Frame(state.copy(), (frame_number + 1) * FRAME_MS,
                f"Result: coherent |A>|B>|(A+B) mod {1 << sum_bits}>; "
                f"A, B = 0…{(1 << input_bits) - 1}; {sum_bits}-bit sum")


def report_progress(frames, total):
    """Report only after the writer has consumed each streamed frame."""
    for index, frame in enumerate(frames, 1):
        yield frame
        if index % 60 == 0 or index == total:
            print(f"Written {index}/{total} frames", flush=True)


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "qft-addition.qls"
    total = 2 + sum(rotation_steps(g.angle) if g.operation == "CP" else 1
                    for _, g in circuit())
    print(f"Writing {total} frames of {N_QUBITS} qubits "
          f"({total * (1 << N_QUBITS) * 4 / 2**20:.0f} MiB of amplitude data)…", flush=True)
    path = write_qls(output, report_progress(addition_history(), total), n=N_QUBITS)
    print(f"{path}: {path.stat().st_size:,} bytes")
    print(f"|{'+' * INPUT_BITS}> + |{'+' * INPUT_BITS}>; "
          f"sum modulo {1 << SUM_BITS}; full |A>|B>|S> state recorded")
