# Qualeidoscope

A small WebGPU viewer for complex amplitudes as a square of colored cells.
Phase controls OKLab hue; magnitude controls brightness. Supports even qubit
counts from 0 to 20 (up to a 1024 × 1024 grid).

## Run the viewer

```sh
python3 qualeidoscope.py
```

Open [localhost:8000](http://localhost:8000) in a browser with WebGPU enabled.
No packages, build step, or internet connection are needed. The server binds only
to the local machine; use `--port 8001` if necessary. WebGPU requires localhost
or HTTPS; opening `index.html` directly is not supported.

In **State → Open recording**, choose a `.qls` file from disk. Start with
[`examples/phase-sweep.qls`](examples/phase-sweep.qls), or explore the
[circuit-history and sparsity demos](examples/README.md). The viewer starts empty
and keeps all file reads local to your browser.

The frame slider and arrow buttons select a frame. **Play** advances in file
order at the chosen speed, initially 5 fps, and stops at the last frame. Pressing
Play at the end restarts from the beginning. Scrubbing and hidden tabs pause
playback. Every frame is shown during playback; slow decoding reduces the
achieved rate instead of accumulating a queue. Timestamps are displayed in
milliseconds and do not set playback timing. No state interpolation is applied.

The current frame's title appears above the grid. The filename, timestamp, and
data statistics stay in the left panel. In landscape, the viewer sits between
the State and color panels; in portrait it occupies the full width above them.
The page stays anchored, with overflow scrolling inside the canvas or panels.

## Explore the colors

- **Phase & magnitude** is an always-visible color key. Phase increases
  counterclockwise from the right; magnitude increases from zero at the center
  to the normalization value at the rim. A ring marks the hovered amplitude;
  a dashed amber ring at the edge means its magnitude exceeds the display scale.
- **Normalization** sets a display scale and snaps to 1 or the current frame's
  peak. A smaller value brightens the image. Selecting the peak follows later
  frames' peaks; manual values persist. An all-zero frame has no peak detent.
- **Amplitude threshold** adjusts the intensity exponent from 0.25 to 16,
  defaulting and snapping to 4. Higher values suppress smaller amplitudes; lower
  values reveal them. Zero stays black and the normalization endpoint stays bright.
- **Global Phase offset** positions the palette. **Animation speed** rotates it
  at 0–180°/s, starting at 90°/s on every page load. Set it to zero when you want
  to see only the changes recorded in your frames. These controls change the
  display, never the loaded data, and are independent of frame playback.
- Hover to inspect values and basis indices in a fixed-width table. Inspection
  shows the values stored in the file, after float16 rounding. Use **1× cells**
  or larger zoom to inspect oversized grids with internal scrollbars; Fit may
  downsample when there are more cells than screen pixels.

The shader uses OKLab hue with saturation adapted to each hue's sRGB gamut.
At full brightness the strongest linear RGB channel reaches one. For
`v = min(abs(amplitude) / normalization, 1)`, `v^threshold` scales linear RGB
intensity before the sRGB transfer function. Alpha is one. Equal magnitudes can
have different perceptual lightness across hues; this palette prioritizes vivid
colors. The grid and wheel share the same mapping. The shader is maintained in
`web/color.wgsl`; there is no shader editor in the interface.

## Write recordings from Python

The writer uses only the standard library:

```python
from math import sqrt
from qls import Frame, write_qls

write_qls("bell.qls", [
    Frame([1, 0, 0, 0], timestamp_ms=0, title="Initial"),
    Frame([1/sqrt(2), 1/sqrt(2), 0, 0], timestamp_ms=100, title="Hadamard"),
    Frame([1/sqrt(2), 0, 0, 1/sqrt(2)], timestamp_ms=200, title="Bell"),
], n=2)
```

Open `bell.qls` in the viewer. Snap Normalization to the peak to use the full color
range for small amplitudes; this does not renormalize the state.

Each frame must contain `2**n` amplitudes. The writer also accepts existing NumPy
arrays via their `.flat` iterator, traversed in C order, without importing NumPy.
If your program produces an iterable called `states`, export it incrementally:

```python
write_qls("history.qls", (
    Frame(state, timestamp_ms=i * 100, title=f"Step {i}")
    for i, state in enumerate(states)
), n=n)
```

The writer consumes each frame before requesting the next, so a producer can
reuse an array. It spools to disk and atomically replaces the destination after
successful validation; it does not keep the entire recording in RAM. NumPy is
optional for producers and is not installed or required by this project.

Read recordings back with:

```python
from qls import Recording

with Recording("bell.qls") as recording:
    frame = recording.read_frame(2)  # Zero-based random access.
    print(frame.title, frame.timestamp_ms, frame.amplitudes)
```

## Data and performance

See [`QLS_FORMAT.md`](QLS_FORMAT.md) for the complete versioned binary format.
Each frame stores a signed **int32 millisecond timestamp**, a UTF-8 title, and
interleaved **float16 real and imaginary components**. Negative, repeated, or
unordered timestamps are allowed; all frames share `n` and the same basis layout.

Float16 storage is lossy relative to complex128. Components must be finite and
within ±65,504; very small values can round to zero. Neither export nor loading
renormalizes the state. The compact recording is intended for visualization.

Layout is row-major: `index = row * 2^(n/2) + column`, starting at the top left.
The most significant `n/2` bits select the row. Convert framework-specific bit
ordering explicitly before export.

The browser indexes metadata once and reads the selected frame with `File.slice()`.
A worker decodes it to float32, which represents every finite float16 component
exactly, for GPU upload and inspection. Rapid scrubbing coalesces pending
selections. At n = 20 a stored frame is 4 MiB, its decoded array is 8 MiB, and GPU
amplitude storage is 8 MiB. Transitions, staging buffers, and render targets need
additional memory. The viewer does not read the whole recording into memory.

Color animation only updates small uniform buffers. Displayed preparation and
upload-enqueue timings measure CPU work, not GPU execution or full frame latency.
Sustained playback and GPU palette performance still need measurements on your
hardware.

## Development and checks

`qls.py` owns Python file I/O; `web/qls.js` reads browser file metadata and slices;
`web/data.js` and `web/data-worker.js` decode amplitudes; `web/renderer.js` owns
WebGPU resources; `web/app.js` coordinates interaction. `qualeidoscope.py` serves
only the static viewer. The previous `.npy` loading and polling workflow has
been replaced by local `.qls` recordings.

```sh
python3 -m unittest discover -s tests -v
python3 examples/generate.py  # Regenerate the three bundled demos.
```

Tests cover file encoding, float16 rounding, int32 boundaries, invalid files,
atomic writes, an n = 20 frame, all bundled demos, and asset serving. Browser
rendering and interaction are reviewed manually; no browser automation package
is included. Check each demo, playback and rapid scrubbing, color controls,
hover values, loading another file, and both landscape and portrait layouts.
