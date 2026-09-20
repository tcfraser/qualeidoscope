# Qualeidoscope

## Vision

Qualeidoscope is an interactive tool for visualizing multi-qubit quantum states.
It turns the complex amplitudes of a state in the computational basis into a
field of colored cells, making structure and change available for visual
exploration.

The tool should be flexible, responsive, and enjoyable to use, with a consistent
visual style. A useful first image should be easy to produce, and deeper control
over layout, color, and animation should remain accessible.

This document records the product vision. The initial prototype decisions and
their rationale are recorded at the end; broader product choices remain open.

## State and spatial representation

An n-qubit pure state has 2^n complex amplitudes:

    |ψ⟩ = Σ aₖ |k⟩,  0 ≤ k < 2^n

Each amplitude corresponds to one computational-basis state and one logical cell.
For even n, the natural display is a square grid of 2^(n/2) × 2^(n/2) cells.
For example, n = 20 produces 1,048,576 cells in a 1024 × 1024 grid.
Cells may occupy individual pixels or larger squares depending on the viewport
and zoom level.

For odd n, an exact square of occupied cells is impossible. Options include a
2^floor(n/2) × 2^ceil(n/2) rectangle or a padded square with clearly distinguished
unused cells. The initial layout policy remains to be chosen.

The mapping from basis indices to positions must be documented, including bit
ordering and which qubits determine each axis. Users should be able to identify
the basis state represented by a cell. Changes in layout must not silently change
the interpretation of imported data.

## GPU color mapping

The GPU shader maps each complex amplitude to an RGBA color. The current product
exposes normalization, amplitude threshold, global phase offset, and animation
speed as sliders. Normalization sets a display scale rather than modifying the
state's norm. Direct shader
editing has been removed from the interface at the user's request. Additional
presets or mappings may be considered later if a concrete need emerges.

The shader interface should expose the real and imaginary components of an
amplitude and make its magnitude and squared magnitude readily available. For
normalized states, the squared magnitude is the computational-basis probability.
Any whole-state norm or display scaling should be explicitly named and distinct
from these per-amplitude quantities. The precise shader contract remains open.

Potential mappings include phase to hue and magnitude or probability to brightness
or opacity. These are starting points for exploration, not fixed encodings.
The interface should explain the active mapping, its scale, and how alpha is
composited against the background.

Rendering must distinguish changes to the underlying state from changes made only
for display. Renormalization, phase adjustments, and automatic brightness scaling
must be explicit. Shader code is maintained in the project rather than edited
through the browser interface.

## State sources and real-time use

Users should be able to prepare circuits in their preferred quantum programming
language and send state snapshots to Qualeidoscope. The renderer should accept
amplitude data through a documented interface without depending on a particular
circuit library. Language-specific adapters can be added when justified by usage.

A snapshot needs amplitudes, a qubit count, and an unambiguous basis-order
convention. The current interchange contract is a local `.qls` recording, with
its numeric precision, complex encoding, and frame metadata specified in
[QLS_FORMAT.md](QLS_FORMAT.md). Live transport remains a future decision.

A second intended workflow is exploring a family of states |ψ(t)⟩. Users should
be able to play, pause, and scrub the parameter t, with clear feedback when state
generation or transfer cannot keep pace. A producer may compute states outside
the renderer; support for visualization does not require a built-in simulator.

Snapshot ingestion, state generation, GPU upload, and display should have separate
responsibilities. Animation needs a bounded buffering policy so that a fast
producer cannot exhaust memory or leave the view far behind the current parameter.
The recording player uses a selectable frame rate in file order, without
interpolation. Timestamps are independent metadata. Live timing and frame-dropping
semantics remain future design decisions; interpolation between snapshots must
not silently imply simulated evolution.

## Performance and platform direction

The initial performance target is around n = 20. This is a practical working
scale, not a universal hard limit or a promise that every device and producer can
animate it at the same rate. Larger states, including the early aspiration of
n = 22, require measurement before becoming a supported target.

State storage grows as 2^n. At n = 20, a single amplitude buffer with two 32-bit
floating-point components per amplitude occupies 8 MiB, before staging buffers,
render targets, or retained snapshots. A small displayed image therefore does
not by itself establish the cost of generating and updating a state.

GPU color mapping is central to the design. Candidate delivery approaches are a
desktop application using a GPU renderer and a browser application using WebGPU.
Select the first platform by weighing installation and sharing, integration with
state producers, shader customization, device support, and sustained update cost.
Supporting both platforms from the outset is not a requirement.

Performance work should measure time to first image, interaction latency, upload
cost, rendering time, and peak memory on representative hardware. Avoid unnecessary
copies and per-cell CPU drawing. Establish frame-rate and capacity targets from
these measurements, and make unsupported workloads understandable to users.

## Experience and first implementation scope

The first complete workflow should let a user open a documented state snapshot,
see it with a useful default shader, understand the basis layout and color mapping,
and change the mapping interactively. A coherent interface, readable controls,
smooth navigation, and useful error messages are part of that workflow.

Subsequent work can extend live snapshot delivery beyond recorded frame playback.
Preserve enough settings to reproduce a view as these
capabilities develop. Integration with every quantum framework, a built-in circuit
editor or simulator, and mixed-state visualization are outside the initial scope.

Before implementation, settle the initial platform, basis layout and odd-n policy,
snapshot contract, shader interface, and normalization/display-scaling behavior.
Record the rationale for each decision in terms of user experience, performance,
and implementation cost.

## Initial prototype decisions

- Start with native browser WebGPU and plain JavaScript modules. This allows
  browser development and deployment without a frontend framework, package
  installation, or build step. A small Python standard-library server serves the
  viewer on localhost. A desktop renderer remains a future option.
- Limit the prototype to even n from 0 through 20. Use row-major grids with the
  most significant bits on the vertical axis and index zero at the top left.
  Odd-qubit layouts remain outside this experiment.
- Store recordings as two float16 components per amplitude, per the requested
  compact file format. This quantizes producer values and can underflow very small
  amplitudes; it is not an exact archival copy of complex128 source data. Decode
  each selected frame in a worker to two float32 components, which preserve all
  finite float16 values exactly and suit WebGPU. Inspection and GPU upload share
  that decoded array. Do not normalize data implicitly.
- Use OKLab hue for phase and adapt saturation to each hue's available sRGB gamut.
  The initial fixed-chroma OKLab palette looked too muted in user review. The
  revised palette uses 95% of each hue's maximum chroma/lightness ratio and scales
  its strongest linear RGB channel to one. The saturation limit is found with a
  bounded 12-step search per fragment; GPU cost needs measurement at larger grids.
  For `v = min(|amplitude| / display_norm, 1)`, scale the resulting linear RGB
  intensity by `v^steepness`, then apply the sRGB display transfer function.
  The exponent is labeled Amplitude threshold and defaults to four, allowing users
  to suppress smaller amplitudes or reveal faint ones. This preserves black at
  zero and reaches full channel intensity at
  the display norm. The palette prioritizes vibrant, saturated colors; equal
  magnitudes no longer imply equal OKLab lightness across different phases.
  The display norm remains separate from the state's L2 norm. Alpha is one.
  Conversion follows the
  [OKLab reference](https://bottosson.github.io/posts/oklab/).
- Start with an empty canvas and load `.qls` files from disk. Bundled examples in
  `examples/` include circuit history, a phase sweep, and increasing sparsity;
  the latter two use unnormalized visual test data to exercise the color range.
  An always-visible wheel
  beside the grid provides a reference for the current mapping: angle is phase,
  and radius scales from zero to the display norm. It uses the same shader pipeline
  and phase offset as the grid. Reference amplitudes
  are synthesized on the GPU; the wheel never replaces the loaded state.
- Anchor the workspace to the browser window: state selection and loading on the
  left, the canvas in the center, and a single color panel on the
  right. Canvas overflow scrolls inside its viewport without moving the controls.
  The phase wheel stays on top, with sliders below; the shader editor and tabs
  have been removed. Branding sits above the left controls, without a page-wide
  header. Landscape keeps three columns with the visualization spanning the
  available height; portrait gives the visualization the full width above both
  menus. Orientation determines this arrangement, including on tablets and tall
  desktop windows. Local panel overflow preserves access on short windows without
  introducing page scrolling.
- Keep hovered-cell details in a single table data row with fixed column widths
  and tabular numerals. Empty placeholders preserve the layout on pointer exit;
  longer values never shift adjacent fields. The detail strip scrolls horizontally
  when needed without moving the canvas or controls.
- Use a logarithmic Normalization slider with exact snap points at one and the data
  peak. The range includes both anchors and the current setting. Selecting the
  peak follows later snapshot peaks; manual values are preserved. Zero and peaks
  below the supported positive scale do not provide a peak detent. Keep phase
  offset as a slider, and replace the animation toggle with a speed slider from
  zero to 180 degrees per second, defaulting to 90°/s on every page load.
  Zero is a stop detent; increasing the slider
  continuously controls the speed without altering the state.
- Use a logarithmic Amplitude threshold slider from 0.25 to 16, with a snap point
  at the default of four. It controls an exponent on relative magnitude in linear
  RGB intensity, keeping hue and saturation fixed. Values above one emphasize the
  largest amplitudes; values below one reveal smaller amplitudes. Both the grid
  and wheel use the same exponent via their existing uniform buffers; adjusting
  it does not upload amplitude data or move the hover marker's coordinates.
- Replace the earlier `.npy` import and polling experiment with `.qls` recordings.
  Each recording has a versioned 32-byte header, a bounded index of signed int32
  millisecond timestamps and UTF-8 titles, then fixed-size float16 amplitude
  blocks. All frames share n and layout, but need not represent related states.
  An indexed binary format enables direct seeking without compression or a ZIP
  dependency. Int32 timestamps avoid BigInt in JavaScript; they are relative
  times spanning about ±24.9 days, not Unix epoch milliseconds. Version 1 limits
  recordings to 100,000 frames and a 16 MiB index; see the format specification.
- Read only metadata and the selected frame from the browser's local File object.
  Keep one file read/decode in flight and coalesce scrub requests to the latest
  selection. A rejected file leaves the previous recording loaded; an invalid
  later frame pauses playback and leaves the previous frame visible. Decoding
  errors are reported when the affected frame is selected.
- Keep file loading, the frame slider, previous/next, playback speed, timestamp,
  and data statistics in the State panel. Display the frame title above the grid.
  Playback follows file order at a selectable rate (initially 5 fps), showing
  every frame and slowing down when loading cannot keep pace. Stop at the last
  frame; Play there restarts the recording. Scrubbing and hidden tabs pause
  playback. No interpolation or timestamp-based scheduling is implied. Global
  phase animation remains independent and starts at 90°/s on page load.
- Provide a standard-library Python writer accepting iterables of frames and
  flat complex iterables or existing NumPy arrays. Spool data to a temporary file,
  then assemble and atomically replace the destination, bounding memory at the
  cost of an extra disk pass. NumPy remains optional and is not installed.
  The viewer and browser demo have no external package dependencies. New external
  dependencies need explanation and user approval. Browser verification is manual
  at the user's request; Playwright is not used.

The current prototype does not yet establish device compatibility, GPU timing, or
an end-to-end frame-rate target. It also does not persist complete view settings.
These remain follow-up work informed by hands-on use and measurement.
