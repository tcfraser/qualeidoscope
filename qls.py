"""Read and write QLS v1 recordings using only the Python standard library."""

from dataclasses import dataclass
import math
import operator
import os
from pathlib import Path
import shutil
import struct
import tempfile

HEADER = struct.Struct("<4sHHIIIIII")
FRAME_INFO = struct.Struct("<iI")
COMPLEX = struct.Struct("<ee")
MAX_N = 20
MAX_FRAMES = 100_000
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_TITLE_BYTES = 1024


@dataclass
class Frame:
    amplitudes: object
    timestamp_ms: int = 0
    title: str = ""


def _qubits(n):
    n = operator.index(n)
    if not 0 <= n <= MAX_N or n % 2:
        raise ValueError("Use an even qubit count n from 0 to 20.")
    return n


def _encode_amplitudes(amplitudes, count):
    # NumPy arrays expose a C-order flat iterator; NumPy is not required here.
    values = iter(amplitudes.flat if hasattr(amplitudes, "flat") else amplitudes)
    data = bytearray(count * COMPLEX.size)
    for k in range(count):
        try:
            value = complex(next(values))
        except StopIteration:
            raise ValueError(f"Each frame must contain exactly {count} amplitudes.") from None
        if (not math.isfinite(value.real) or not math.isfinite(value.imag)
                or max(abs(value.real), abs(value.imag)) > 65504):
            raise ValueError("Amplitude components must be finite and within float16 range (±65504).")
        COMPLEX.pack_into(data, k * COMPLEX.size, value.real, value.imag)
    sentinel = object()
    if next(values, sentinel) is not sentinel:
        raise ValueError(f"Each frame must contain exactly {count} amplitudes.")
    return data


def write_qls(path, frames, *, n):
    """Atomically write an iterable of Frames, processing one amplitude array at a time.

    Components are rounded to IEEE binary16; very small values can become zero.
    Values are never normalized. Timestamps are signed int32 milliseconds.
    """
    n = _qubits(n)
    path = Path(path).resolve()
    index = bytearray()
    frame_count = 0
    with tempfile.TemporaryFile(dir=path.parent) as payload:
        for frame in frames:
            if frame_count >= MAX_FRAMES:
                raise ValueError(f"At most {MAX_FRAMES} frames are supported.")
            timestamp = operator.index(frame.timestamp_ms)
            if not -(2**31) <= timestamp < 2**31:
                raise ValueError("Timestamps must fit in signed int32 milliseconds.")
            if not isinstance(frame.title, str):
                raise TypeError("Frame titles must be strings.")
            title = frame.title.encode("utf-8")
            if len(title) > MAX_TITLE_BYTES:
                raise ValueError(f"Titles must fit in {MAX_TITLE_BYTES} UTF-8 bytes.")
            entry = FRAME_INFO.pack(timestamp, len(title)) + title + bytes(-len(title) % 4)
            if len(index) + len(entry) > MAX_INDEX_BYTES:
                raise ValueError("The frame index exceeds 16 MiB.")
            payload.write(_encode_amplitudes(frame.amplitudes, 2**n))
            index.extend(entry)
            frame_count += 1
        if frame_count == 0:
            raise ValueError("A recording must contain at least one frame.")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".qls.tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(HEADER.pack(b"QLS\0", 1, 0, n, frame_count, len(index), 0, 0, 0))
                output.write(index)
                payload.seek(0)
                shutil.copyfileobj(payload, output)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return path


class Recording:
    """An indexed QLS reader. read_frame() only reads the requested amplitude array."""

    def __init__(self, path):
        self.file = Path(path).open("rb")
        try:
            self._read_index()
        except Exception:
            self.close()
            raise

    def _read_index(self):
        header = self.file.read(HEADER.size)
        if len(header) != HEADER.size:
            raise ValueError("The QLS header is truncated.")
        magic, version, flags, n, count, size, r0, r1, r2 = HEADER.unpack(header)
        if magic != b"QLS\0" or version != 1:
            raise ValueError("Expected a QLS version 1 recording.")
        if flags or r0 or r1 or r2:
            raise ValueError("Unsupported QLS flags or reserved fields.")
        self.n = _qubits(n)
        if not 1 <= count <= MAX_FRAMES:
            raise ValueError("Invalid QLS frame count.")
        if not count * FRAME_INFO.size <= size <= MAX_INDEX_BYTES:
            raise ValueError("Invalid QLS index size.")
        self.frame_bytes = COMPLEX.size * 2**n
        self.data_offset = HEADER.size + size
        if os.fstat(self.file.fileno()).st_size != self.data_offset + count * self.frame_bytes:
            raise ValueError("QLS file size does not match its header.")
        index = self.file.read(size)
        if len(index) != size:
            raise ValueError("The QLS index is truncated.")
        self.frames = []
        offset = 0
        for _ in range(count):
            if offset + FRAME_INFO.size > size:
                raise ValueError("The QLS index is truncated.")
            timestamp, length = FRAME_INFO.unpack_from(index, offset)
            offset += FRAME_INFO.size
            padded = length + (-length % 4)
            if length > MAX_TITLE_BYTES or offset + padded > size:
                raise ValueError("Invalid QLS title length.")
            title = index[offset:offset + length].decode("utf-8", errors="strict")
            if any(index[offset + length:offset + padded]):
                raise ValueError("QLS title padding must be zero.")
            self.frames.append((timestamp, title))
            offset += padded
        if offset != size:
            raise ValueError("Unexpected trailing QLS index data.")

    def __len__(self):
        return len(self.frames)

    def read_frame(self, index):
        index = operator.index(index)
        if not 0 <= index < len(self):
            raise IndexError("Frame index is outside the recording.")
        self.file.seek(self.data_offset + index * self.frame_bytes)
        data = self.file.read(self.frame_bytes)
        if len(data) != self.frame_bytes:
            raise ValueError("The QLS frame is truncated.")
        amplitudes = []
        for real, imaginary in struct.iter_unpack("<ee", data):
            if not math.isfinite(real) or not math.isfinite(imaginary):
                raise ValueError("QLS amplitudes must be finite.")
            amplitudes.append(complex(real, imaginary))
        timestamp, title = self.frames[index]
        return Frame(amplitudes, timestamp, title)

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
