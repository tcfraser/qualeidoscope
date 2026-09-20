// QLS v1: indexed metadata, followed by fixed-size interleaved float16 frames.
const HEADER_BYTES = 32;
const MAX_FRAMES = 100_000;
const MAX_INDEX_BYTES = 16 * 1024 * 1024;
const MAX_TITLE_BYTES = 1024;

export function parseHeader(buffer, fileSize) {
  if (buffer.byteLength !== HEADER_BYTES) throw new Error("The QLS header is truncated.");
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  if (![81, 76, 83, 0].every((value, i) => bytes[i] === value) || view.getUint16(4, true) !== 1) {
    throw new Error("Choose a QLS version 1 (.qls) recording.");
  }
  if (view.getUint16(6, true) || [20, 24, 28].some(offset => view.getUint32(offset, true))) {
    throw new Error("This recording uses unsupported QLS flags or reserved fields.");
  }
  const n = view.getUint32(8, true);
  const count = view.getUint32(12, true);
  const indexBytes = view.getUint32(16, true);
  if (n > 20 || n % 2) throw new Error("Use an even qubit count n from 0 to 20.");
  if (count < 1 || count > MAX_FRAMES) throw new Error("A recording must contain 1–100,000 frames.");
  if (indexBytes < count * 8 || indexBytes > MAX_INDEX_BYTES) throw new Error("Invalid QLS frame index size.");
  const frameBytes = 4 * 2 ** n;
  const dataOffset = HEADER_BYTES + indexBytes;
  if (!Number.isSafeInteger(fileSize) || fileSize !== dataOffset + count * frameBytes) {
    throw new Error("The recording's size does not match its header. It may be incomplete.");
  }
  return { n, count, indexBytes, frameBytes, dataOffset };
}

export function parseIndex(buffer, count) {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  const frames = [];
  let offset = 0;
  for (let i = 0; i < count; i++) {
    if (offset + 8 > buffer.byteLength) throw new Error("The QLS frame index is truncated.");
    const timestamp = view.getInt32(offset, true);
    const length = view.getUint32(offset + 4, true);
    offset += 8;
    const padded = Math.ceil(length / 4) * 4;
    if (length > MAX_TITLE_BYTES || offset + padded > buffer.byteLength) throw new Error("Invalid QLS frame title length.");
    let title;
    try { title = decoder.decode(bytes.subarray(offset, offset + length)); }
    catch { throw new Error("A frame title is not valid UTF-8."); }
    if (bytes.subarray(offset + length, offset + padded).some(value => value !== 0)) {
      throw new Error("QLS title padding must be zero.");
    }
    frames.push({ timestamp, title });
    offset += padded;
  }
  if (offset !== buffer.byteLength) throw new Error("Unexpected trailing QLS index data.");
  return frames;
}

export async function openRecording(file) {
  const header = parseHeader(await file.slice(0, HEADER_BYTES).arrayBuffer(), file.size);
  const index = await file.slice(HEADER_BYTES, header.dataOffset).arrayBuffer();
  if (index.byteLength !== header.indexBytes) throw new Error("The QLS frame index is truncated.");
  return { ...header, file, frames: parseIndex(index, header.count) };
}

export async function readFrame(recording, index) {
  if (!Number.isInteger(index) || index < 0 || index >= recording.count) throw new Error("Frame index is outside the recording.");
  const offset = recording.dataOffset + index * recording.frameBytes;
  const buffer = await recording.file.slice(offset, offset + recording.frameBytes).arrayBuffer();
  if (buffer.byteLength !== recording.frameBytes) throw new Error("The QLS frame is truncated. Try reopening the file.");
  return buffer;
}
