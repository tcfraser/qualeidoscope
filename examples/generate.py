"""Regenerate the bundled QLS demos: python3 examples/generate.py."""

import cmath
import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qls import Frame, write_qls


def circuit_history():
    state = [0j] * 256
    state[0] = 1
    yield Frame(state, 0, "Initial |0⟩")
    state[0] = state[1] = 1 / math.sqrt(2)
    yield Frame(state, 250, "Hadamard q0")
    for target in range(1, 8):
        updated = [0j] * len(state)
        for k, value in enumerate(state):
            updated[k ^ (1 << target) if k & 1 else k] = value
        state = updated
        yield Frame(state, 250 * (target + 1), f"CNOT q0 → q{target}")
    state[-1] *= 1j
    yield Frame(state, 2250, "GHZ with phase π/2")


def phase_history():
    rng = random.Random(42)
    initial = [cmath.rect(math.sqrt(rng.random()), rng.random() * math.tau) for _ in range(4096)]
    for frame in range(24):
        values = [value * cmath.exp(1j * math.tau * frame / 24 * (2 * (k % 64) / 63 - 1))
                  for k, value in enumerate(initial)]
        yield Frame(values, frame * 100, f"Phase sweep {frame + 1:02d}")


def sparsity_history():
    rng = random.Random(7)
    initial = [(math.sqrt(rng.random()), rng.random() * math.tau) for _ in range(4096)]
    for frame in range(12):
        power = 1 + frame * 2
        values = [cmath.rect(radius**power, phase) if radius**power >= 0.01 else 0j
                  for radius, phase in initial]
        yield Frame(values, frame * 200, f"Sparsity {frame + 1:02d}")


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    for name, n, frames in [("circuit-history", 8, circuit_history()),
                            ("phase-sweep", 12, phase_history()),
                            ("sparsity", 12, sparsity_history())]:
        path = write_qls(directory / f"{name}.qls", frames, n=n)
        print(f"{path.name}: {path.stat().st_size:,} bytes")
