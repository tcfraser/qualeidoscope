r"""Read and write QLS v1 recordings using only the Python standard library.

# QLS version 1

A `.qls` recording contains an ordered list of frames with a shared qubit count
and computational-basis layout. Frames may represent circuit history, a parameter
sweep, or unrelated states. All integers and floating-point values are little
endian. There is no compression or pickled content.

## Header

The header is exactly 32 bytes; its Python `struct` format is `<4sHHIIIIII`.

| Byte offset | Type | Meaning |
| --- | --- | --- |
| 0 | 4 bytes | Magic: `51 4c 53 00` (`QLS\0`) |
| 4 | uint16 | Version: `1` |
| 6 | uint16 | Flags: `0` |
| 8 | uint32 | Qubit count `n`, even and between 0 and 20 |
| 12 | uint32 | Frame count `L`, between 1 and 100,000 |
| 16 | uint32 | Total frame-index size in bytes, at most 16 MiB |
| 20 | 3 × uint32 | Reserved, all zero |

The version, flags and reserved fields allow future formats to fail clearly in
older readers. These limits describe the current format and prototype.

## Frame index

Immediately after the header, there are `L` entries in playback order:

| Type | Meaning |
| --- | --- |
| **int32** | Timestamp, in milliseconds relative to a producer-chosen origin |
| uint32 | UTF-8 title length in bytes, at most 1,024 |
| byte array | UTF-8 title, no terminating NUL; an empty title is allowed |
| 0–3 zero bytes | Padding to the next multiple of four bytes |

Each entry occupies `8 + ceil(title_bytes / 4) * 4` bytes. The header's index
size must exactly match the sum of entry sizes. Titles must be valid UTF-8;
title content is displayed as text, never HTML.

Timestamp range is −2,147,483,648 to 2,147,483,647 milliseconds (about ±24.9 days).
Values are exactly representable by JavaScript `Number` and read with
`DataView.getInt32(offset, true)`. These are relative timestamps, not Unix epoch
milliseconds. Negative, repeated, and nonmonotonic values are permitted.

Playback uses file order at a user-selected frame rate. Timestamps are displayed
as metadata and do not control playback timing. There is no interpolation.

## Amplitude blocks

After the index come `L` contiguous blocks. Each block contains exactly `2^n`
complex amplitudes in row-major order, encoded as:

```text
real[0]: float16, imaginary[0]: float16,
real[1]: float16, imaginary[1]: float16, ...
```

`float16` means IEEE 754 binary16 (two bytes), making each complex amplitude four
bytes. Components must be finite, including subnormal values and signed zero.
NaN and infinity are invalid. Python's `struct` format for one amplitude is `<ee`.
NumPy producers can express this storage as a little-endian float16 array of
shape `(2**n, 2)`; it is not a NumPy complex dtype or a `.npy` file.

For a zero-based frame index `i`:

```text
frame_bytes = 4 * 2^n
frame_offset = 32 + index_bytes + i * frame_bytes
file_bytes = 32 + index_bytes + L * frame_bytes
```

The file must match this length exactly; trailing data is invalid. Readers must
use arithmetic that supports offsets beyond 4 GiB (ordinary JavaScript `Number`
arithmetic is sufficient under these limits; bitwise offset arithmetic is not).

The grid side is `2^(n/2)`, and `index = row * side + column`, with index zero
at the top left. The most significant `n/2` bits select the row. Producers must
convert any framework-specific ordering before writing the file.

## Precision and loading

The writer rounds each component to float16, whose largest finite magnitude is
65,504. Small values lose relative precision near zero and may round to zero;
the smallest positive subnormal is `2^-24`. A `.qls` file is a compact visual
recording, and does not preserve an original complex128 array's precision.
No writer or reader renormalizes the amplitudes.

The browser reads only the header, bounded index, and the selected frame using
`File.slice()`. It validates metadata when opening the recording and validates
amplitudes when their frame is decoded. A malformed later frame stops playback
and leaves the previous frame visible.

A worker expands the selected frame to float32 for both GPU upload and hover
inspection. All finite float16 components are exactly representable in float32.
At `n = 20`, a stored frame is 4 MiB, its decoded array is 8 MiB, and its GPU
storage buffer is 8 MiB. An old frame, an in-flight replacement, browser upload
staging, and render targets add to peak memory. Only one file read/decode is in
flight; stale scrub selections are discarded before upload. Total file length
does not determine retained amplitude memory. Sustained frame rate depends on
disk access, decoding, upload, and hardware, and has not yet been benchmarked.

## Python interface

This module provides `Frame(amplitudes, timestamp_ms=0, title="")`,
`write_qls(path, frames, n=...)`, and a context-managed `Recording(path)` reader.
The writer accepts an iterable of frames and consumes each amplitude array before
requesting the next frame, so producers can reuse or update an array between
yields. Flat Python iterables and NumPy arrays exposing `.flat` are supported;
the latter are traversed in C order. Exactly `2^n` values are required per frame.

The writer spools frame data to a temporary file while collecting the index,
then assembles and atomically replaces the destination. Memory stays bounded by
one frame plus the index; writing temporarily needs roughly twice the recording's
disk space, in addition to any existing destination. A failed write leaves the
previous destination intact. No external package is required.
"""

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
