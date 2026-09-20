import { decodeFrame } from "./data.js";

self.onmessage = ({ data }) => {
  try {
    const start = performance.now();
    const result = decodeFrame(data.buffer, data.n);
    self.postMessage({ id: data.id, ...result, preparationMs: performance.now() - start },
      [result.values.buffer]);
  } catch (error) {
    self.postMessage({ id: data.id, error: error.message });
  }
};
