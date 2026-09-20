// Decode binary16 explicitly; no browser Float16Array support is required.
export function halfToNumber(bits) {
  const sign = bits & 0x8000 ? -1 : 1;
  const exponent = (bits >>> 10) & 31;
  const fraction = bits & 1023;
  if (exponent === 31) return fraction ? NaN : sign * Infinity;
  if (exponent === 0) return sign * fraction * 2 ** -24;
  return sign * (1 + fraction / 1024) * 2 ** (exponent - 15);
}

export function decodeFrame(buffer, n) {
  if (!Number.isInteger(n) || n < 0 || n > 20 || n % 2) throw new Error("Use an even qubit count n from 0 to 20.");
  const count = 2 ** n;
  if (buffer.byteLength !== count * 4) throw new Error("The QLS frame has the wrong size.");
  const view = new DataView(buffer);
  const values = new Float32Array(count * 2);
  let peak = 0, sumSquares = 0;
  for (let k = 0; k < values.length; k += 2) {
    const real = halfToNumber(view.getUint16(k * 2, true));
    const imaginary = halfToNumber(view.getUint16(k * 2 + 2, true));
    if (!Number.isFinite(real) || !Number.isFinite(imaginary)) throw new Error("QLS amplitudes must be finite.");
    values[k] = real;
    values[k + 1] = imaginary;
    const magnitude = Math.hypot(real, imaginary);
    peak = Math.max(peak, magnitude);
    sumSquares += magnitude * magnitude;
  }
  // Every finite float16 value is exactly representable in float32. The same
  // array supplies hover inspection and GPU upload, avoiding a redundant copy.
  return { values, side: 2 ** (n / 2), peak, l2: Math.sqrt(sumSquares) };
}
