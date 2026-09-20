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

[`qls.py`](qls.py) provides `Frame(amplitudes, timestamp_ms=0, title="")`,
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
