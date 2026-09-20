# Demo recordings

Open these files from the viewer's **State → Open recording** control.

| File | Grid | Frames | Content |
| --- | --- | --- | --- |
| `circuit-history.qls` | 16 × 16 | 10 | Hadamard and CNOT steps preparing an eight-qubit GHZ state, then a relative phase change |
| `phase-sweep.qls` | 64 × 64 | 24 | Seeded unit-disk samples with phase changing across columns |
| `sparsity.qls` | 64 × 64 | 12 | Progressively suppressed magnitudes, with tiny amplitudes set to zero |

The circuit example starts with L2-normalized states; float16 storage introduces
small rounding errors. Qubit zero is the least significant basis-index bit.
The phase and sparsity examples are unnormalized visual test data, not simulated
quantum evolution. Their magnitudes near one exercise the default color scale.

Scrub with the frame slider, or press **Play**. Titles and timestamps are stored
in the files. Playback follows frame order at the selected speed; timestamps are
independent metadata. Set the color panel's **Animation speed** to zero to isolate
the changes recorded in the files from display-only phase rotation.

Regenerate the same recordings from the repository root with:

```sh
python3 examples/generate.py
```

This uses only Python's standard library and overwrites these three demo files.
See [`generate.py`](generate.py) for small producer examples and
[`QLS_FORMAT.md`](../QLS_FORMAT.md) for the file specification.
