import { openRecording, readFrame } from "./qls.js";
import { Renderer } from "./renderer.js?v=2";

const $ = id => document.getElementById(id);
const canvas = $("canvas");
const legendCanvas = $("phase-wheel");
const inspectionCells = ["basis", "index", "row", "column", "real", "imaginary", "magnitude", "probability", "phase"]
  .map(name => $(`inspect-${name}`));
const worker = new Worker(new URL("./data-worker.js", import.meta.url), { type: "module" });
const pending = new Map();
let nextJob = 0;
let renderer, snapshot;
let norm = 1, phase = 0, speed = 90, steepness = 4, frame = null, previousTime = null;
let normLow = -1, normHigh = 1, normAnchor = "unit", normSnaps = [];
let recording = null, currentIndex = -1, wantedIndex = -1;
let busy = false, generation = 0, loadTask = null;
let playing = false, playbackTimer = null, nextFrameAt = 0;
let workerFailure = null;
let hoverPointer = null;

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

worker.onmessage = ({ data }) => {
  const job = pending.get(data.id);
  if (!job) return;
  pending.delete(data.id);
  if (data.error) job.reject(new Error(data.error));
  else job.resolve(data);
};
worker.onerror = event => {
  const error = new Error(event.message || "Could not start the data worker. Reload the page to retry.");
  workerFailure = error;
  pausePlayback();
  for (const job of pending.values()) job.reject(error);
  pending.clear();
  showError(error.message);
};

function prepare(data) {
  if (workerFailure) return Promise.reject(workerFailure);
  return new Promise((resolve, reject) => {
    const id = ++nextJob;
    pending.set(id, { resolve, reject });
    try { worker.postMessage({ id, ...data }, [data.buffer]); }
    catch (error) { pending.delete(id); reject(error); }
  });
}

function requestDraw() {
  if (frame === null) frame = requestAnimationFrame(draw);
}

function draw(time) {
  frame = null;
  if (renderer && speed > 0 && !document.hidden) {
    if (previousTime !== null) phase = (phase + Math.min(time - previousTime, 100) / 1000 * speed * Math.PI / 180) % (2 * Math.PI);
    $("phase").value = phase * 180 / Math.PI;
    $("phase-value").value = `${Math.round(phase * 180 / Math.PI)}°`;
    previousTime = time;
    requestDraw();
  } else previousTime = null;
  try { renderer?.draw(norm, phase, steepness); }
  catch (error) {
    setSpeed(0);
    showError(error.message);
  }
}

function resize() {
  if (!renderer) return;
  if (snapshot) resizeCanvas();
  const legendPixels = Math.max(1, Math.min(renderer.device.limits.maxTextureDimension2D,
    Math.round(legendCanvas.getBoundingClientRect().width * devicePixelRatio)));
  if (legendCanvas.width !== legendPixels || legendCanvas.height !== legendPixels) {
    legendCanvas.width = legendCanvas.height = legendPixels;
  }
  updateHover();
  requestDraw();
}

function resizeCanvas() {
  const viewport = $("viewport");
  const zoom = $("zoom").value;
  const cssSide = zoom === "fit"
    ? Math.max(1, Math.min(viewport.clientWidth - 26, viewport.clientHeight - 26))
    : snapshot.side * Number(zoom);
  canvas.style.width = `${cssSide}px`;
  canvas.style.height = `${cssSide}px`;
  // Render at least one sample per cell. CSS may downsample in Fit view.
  const pixels = Math.min(renderer.device.limits.maxTextureDimension2D,
    Math.max(snapshot.side, Math.round(cssSide * devicePixelRatio)));
  if (canvas.width !== pixels || canvas.height !== pixels) {
    canvas.width = pixels;
    canvas.height = pixels;
  }
}

function setBusy(value) {
  busy = value;
  $("file").disabled = value;
  updateFrameControls();
}

function useSnapshot(data) {
  const start = performance.now();
  renderer.upload(data.values, data.side);
  const enqueueMs = performance.now() - start;
  snapshot = data;
  canvas.hidden = false;
  $("empty-state").hidden = true;
  updateNormSlider();
  const m = Math.log2(data.side);
  $("dimensions").textContent = `${data.side.toLocaleString()} × ${data.side.toLocaleString()} cells · ${m * 2} qubits`;
  $("status").textContent = `${(data.side ** 2).toLocaleString()} amplitudes · peak |a| ${data.peak.toPrecision(4)} · state L2 norm ${data.l2.toPrecision(4)} · preparation ${data.preparationMs.toFixed(1)} ms · upload enqueue ${enqueueMs.toFixed(1)} ms (CPU)`;
  setInspection();
  showError("");
  resize();
}

async function openFile(file) {
  if (!file || busy) return;
  pausePlayback();
  generation++;
  wantedIndex = currentIndex;
  setBusy(true);
  try {
    // Let the one outstanding read finish before starting another. Its generation
    // is now stale, so it cannot replace the view while this file is opening.
    await loadTask;
    const candidate = await openRecording(file);
    const data = await prepare({ buffer: await readFrame(candidate, 0), n: candidate.n });
    useSnapshot(data);
    recording = candidate;
    currentIndex = wantedIndex = 0;
    $("source").textContent = file.name;
    updateFrameDetails();
  } catch (error) { showError(error.message); }
  finally { setBusy(false); $("file").value = ""; }
}

function updateFrameDetails() {
  const metadata = recording.frames[currentIndex];
  const title = metadata.title || `Frame ${currentIndex + 1}`;
  $("frame-title").textContent = title;
  $("frame-title").title = title;
  $("timestamp").textContent = `Time: ${metadata.timestamp.toLocaleString()} ms`;
}

function updateFrameControls() {
  const count = recording?.count || 0;
  $("frame-controls").disabled = busy || count === 0;
  $("frame-select").disabled = count < 2;
  $("frame-select").max = Math.max(0, count - 1);
  $("frame-select").value = Math.max(0, wantedIndex);
  $("frame-select").setAttribute("aria-valuetext", count ? `Frame ${wantedIndex + 1} of ${count}` : "No recording loaded");
  $("frame-value").value = count ? `${wantedIndex + 1} / ${count}` : "— / —";
  $("previous").disabled = wantedIndex <= 0;
  $("next").disabled = count === 0 || wantedIndex >= count - 1;
  $("play").disabled = count < 2;
  $("fps").disabled = count < 2;
  $("play").textContent = playing ? "Pause" : "Play";
  $("play").setAttribute("aria-pressed", String(playing));
  const loading = busy || Boolean(loadTask);
  $("viewport").setAttribute("aria-busy", String(loading));
  $("load-status").hidden = !loading;
  $("load-status").textContent = busy ? "Opening recording…" : `Loading frame ${wantedIndex + 1}…`;
}

function pausePlayback() {
  playing = false;
  clearTimeout(playbackTimer);
  playbackTimer = null;
  updateFrameControls();
}

function schedulePlayback() {
  clearTimeout(playbackTimer);
  playbackTimer = null;
  if (!playing || busy || loadTask) return;
  if (document.hidden || currentIndex >= recording.count - 1) {
    pausePlayback();
    return;
  }
  playbackTimer = setTimeout(() => {
    nextFrameAt = performance.now() + 1000 / Number($("fps").value);
    wantedIndex = currentIndex + 1;
    requestFrame();
  }, Math.max(0, nextFrameAt - performance.now()));
}

function requestFrame() {
  if (loadTask || busy || !recording || wantedIndex === currentIndex) {
    updateFrameControls();
    return;
  }
  loadTask = (async () => {
    try {
      while (!busy && wantedIndex !== currentIndex) {
        const index = wantedIndex, token = generation;
        try {
          const buffer = await readFrame(recording, index);
          if (busy || token !== generation) return;
          if (index !== wantedIndex) continue;
          const data = await prepare({ buffer, n: recording.n });
          if (busy || token !== generation) return;
          if (index !== wantedIndex) continue;
          useSnapshot(data);
          currentIndex = index;
          updateFrameDetails();
        } catch (error) {
          if (busy || token !== generation) return;
          if (index !== wantedIndex) continue;
          wantedIndex = currentIndex;
          pausePlayback();
          showError(`Frame ${index + 1}: ${error.message}`);
          break;
        }
      }
    } finally {
      loadTask = null;
      updateFrameControls();
      schedulePlayback();
    }
  })();
  updateFrameControls();
}

function selectFrame(index) {
  if (busy || !recording) return;
  pausePlayback();
  wantedIndex = Math.max(0, Math.min(recording.count - 1, index));
  requestFrame();
}

function togglePlayback() {
  if (playing) { pausePlayback(); return; }
  if (busy || !recording || recording.count < 2) return;
  playing = true;
  nextFrameAt = performance.now() + 1000 / Number($("fps").value);
  if (wantedIndex >= recording.count - 1) wantedIndex = 0;
  requestFrame();
  schedulePlayback();
}

const formatValue = value => Number(value.toPrecision(6)).toString();
const normPosition = value => 1000 * (Math.log10(value) - normLow) / (normHigh - normLow);

// Keep a fractional position for exact detents even though the native range's
// keyboard step is integral. Keyboard movement crosses a detent once, then leaves
// it on the next press; pointer movement has a small magnetic region around it.
function snappingRange(slider, getSnaps, onChange) {
  let keyboard = false, key = "", previous = Number(slider.value);
  slider.addEventListener("pointerdown", () => { keyboard = false; key = ""; });
  slider.addEventListener("keydown", event => { keyboard = true; key = event.key; });
  const move = position => { previous = position; slider.value = position; };
  slider.addEventListener("input", () => {
    const position = Number(slider.value);
    const direction = Math.sign(position - previous);
    const snaps = getSnaps();
    const radius = 5 * (Number(slider.max) - Number(slider.min)) / Math.max(slider.clientWidth, 1);
    const crossed = snap => direction > 0
      ? snap.position > previous + 1e-7 && snap.position <= position
      : snap.position < previous - 1e-7 && snap.position >= position;
    const candidates = snaps.filter(snap => keyboard
      ? (["Home", "End"].includes(key) ? snap.position === position : crossed(snap))
      : Math.abs(snap.position - position) <= radius);
    candidates.sort((a, b) => Math.abs(a.position - (keyboard ? previous : position)) - Math.abs(b.position - (keyboard ? previous : position)));
    const snap = candidates[0];
    move(snap ? snap.position : position);
    onChange(snap ? snap.position : position, snap);
  });
  return move;
}

function displayNorm() {
  const value = formatValue(norm);
  $("norm-value").value = value;
  $("norm-value").title = String(norm);
  $("wheel-norm").value = value;
  $("norm").setAttribute("aria-valuetext", `${value}${normAnchor === "peak" ? ", data peak" : normAnchor === "unit" ? ", unit scale" : ""}`);
  updateHover();
  requestDraw();
}

const moveNorm = snappingRange($("norm"), () => normSnaps, (position, snap) => {
  normAnchor = snap?.name || null;
  norm = snap ? snap.value : 10 ** (normLow + position / 1000 * (normHigh - normLow));
  displayNorm();
});

function updateNormSlider() {
  const peak = snapshot?.peak || 0;
  const validPeak = peak >= 1e-30 && peak <= 1e30;
  if (normAnchor === "peak") {
    norm = validPeak ? peak : 1;
    if (!validPeak) normAnchor = "unit";
  }
  // A logarithmic scale keeps normalized, million-amplitude states easy to reach.
  // Include the current value so loading another state does not reset manual scale.
  const low = Math.min(1, norm, validPeak ? peak : 1);
  const high = Math.max(1, norm, validPeak ? peak : 1);
  normLow = Math.max(-30, Math.log10(low / 16));
  normHigh = Math.min(30, Math.log10(high * 4));
  normSnaps = [{ name: "unit", value: 1, position: normPosition(1) }];
  if (validPeak && peak !== 1) normSnaps.push({ name: "peak", value: peak, position: normPosition(peak) });
  $("norm-marks").replaceChildren(...normSnaps.map(snap => {
    const mark = document.createElement("span");
    mark.style.left = `${snap.position / 10}%`;
    mark.title = snap.name === "unit" ? "1" : `Peak ${formatValue(peak)}`;
    return mark;
  }));
  $("norm-hint").textContent = !snapshot
    ? "Snaps to 1. Load a recording to add its data peak."
    : validPeak
    ? `Snaps to 1 and peak ${formatValue(peak)}. Logarithmic scale.`
    : `Snaps to 1. Peak ${formatValue(peak)} is below the positive display range.`;
  moveNorm(normPosition(norm));
  displayNorm();
}

function setSpeed(value) {
  speed = value;
  $("speed").value = value;
  const label = value === 0 ? "Stopped" : `${value}°/s`;
  $("speed-value").value = label;
  $("speed").setAttribute("aria-valuetext", label);
  previousTime = null;
}
snappingRange($("speed"), () => [{ position: 0 }], position => {
  setSpeed(position);
  requestDraw();
});
snappingRange($("steepness"), () => [{ position: 400 }], position => {
  steepness = 2 ** (position / 100 - 2);
  const label = Number(steepness.toPrecision(3)).toString();
  $("steepness-value").value = label;
  $("steepness").setAttribute("aria-valuetext", `${label}${steepness === 4 ? ", default" : ""}`);
  requestDraw();
});

function setInspection(values = []) {
  for (let i = 0; i < inspectionCells.length; i++) {
    const text = values[i] === undefined ? "—" : String(values[i]);
    inspectionCells[i].textContent = text;
    inspectionCells[i].title = text === "—" ? "Hover over a cell to inspect it" : text;
  }
}

function updateHover() {
  const marker = $("wheel-marker");
  if (!snapshot || !hoverPointer) {
    marker.hidden = true;
    setInspection();
    return;
  }
  const bounds = canvas.getBoundingClientRect();
  const viewport = $("viewport");
  const clip = viewport.getBoundingClientRect();
  const { x, y } = hoverPointer;
  if (x < bounds.left || x >= bounds.right || y < bounds.top || y >= bounds.bottom
      || x < clip.left + viewport.clientLeft || x >= clip.left + viewport.clientLeft + viewport.clientWidth
      || y < clip.top + viewport.clientTop || y >= clip.top + viewport.clientTop + viewport.clientHeight) {
    marker.hidden = true;
    setInspection();
    return;
  }
  const col = Math.min(snapshot.side - 1, Math.floor((x - bounds.left) / bounds.width * snapshot.side));
  const row = Math.min(snapshot.side - 1, Math.floor((y - bounds.top) / bounds.height * snapshot.side));
  const k = row * snapshot.side + col;
  const re = snapshot.values[k * 2], im = snapshot.values[k * 2 + 1];
  const magnitude = Math.hypot(re, im);
  const bits = k.toString(2).padStart(2 * Math.log2(snapshot.side), "0");
  const angle = magnitude === 0 ? "undefined" : `${(Math.atan2(im, re) * 180 / Math.PI).toFixed(2)}°`;
  const clipped = magnitude > norm;
  setInspection([
    `|${bits}⟩`, k, row, col,
    re.toPrecision(5), im.toPrecision(5),
    magnitude.toPrecision(5), (magnitude ** 2).toPrecision(5), angle,
  ]);
  // The wheel's shader already applies the global phase offset, just like the
  // grid. Plot the original amplitude here to avoid applying that offset twice.
  const divisor = Math.max(norm, magnitude);
  marker.style.left = `${50 + 50 * re / divisor}%`;
  marker.style.top = `${50 - 50 * im / divisor}%`;
  marker.dataset.clipped = String(clipped);
  marker.hidden = false;
}

canvas.addEventListener("pointermove", event => {
  hoverPointer = { x: event.clientX, y: event.clientY };
  updateHover();
});
function clearHover() {
  hoverPointer = null;
  $("wheel-marker").hidden = true;
  setInspection();
}
canvas.addEventListener("pointerleave", clearHover);
canvas.addEventListener("pointercancel", clearHover);
$("viewport").addEventListener("scroll", updateHover, { passive: true });

$("file").onchange = event => openFile(event.target.files[0]);
$("frame-select").oninput = () => selectFrame(Number($("frame-select").value));
$("previous").onclick = () => selectFrame(wantedIndex - 1);
$("next").onclick = () => selectFrame(wantedIndex + 1);
$("play").onclick = togglePlayback;
$("fps").onchange = () => {
  nextFrameAt = performance.now() + 1000 / Number($("fps").value);
  schedulePlayback();
};
$("zoom").onchange = resize;
$("phase").oninput = () => {
  phase = Number($("phase").value) * Math.PI / 180;
  $("phase-value").value = `${$("phase").value}°`;
  requestDraw();
};
document.addEventListener("visibilitychange", () => {
  previousTime = null;
  if (document.hidden) pausePlayback();
  requestDraw();
});
new ResizeObserver(resize).observe($("viewport"));
new ResizeObserver(resize).observe(legendCanvas);
window.addEventListener("resize", resize);

async function start() {
  try {
    renderer = await Renderer.create(canvas, legendCanvas, showError);
    const response = await fetch("./color.wgsl", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load color.wgsl.");
    await renderer.setShader(await response.text());
    // A single zero supplies the storage binding until a recording is loaded,
    // allowing the color key to remain visible in the empty state.
    renderer.upload(new Float32Array(2), 1);
    $("controls").disabled = false;
    $("state-controls").disabled = false;
    $("status").textContent = "Ready to open a recording.";
    updateNormSlider();
    updateFrameControls();
    resize();
  } catch (error) {
    $("status").textContent = "The renderer could not start.";
    showError(error.message);
  }
}

start();
