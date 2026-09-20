"""QLS wire-format, quantization, validation and atomic-write checks."""

import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import qls
from qls import Frame, Recording, write_qls


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "test.qls"

    def valid_bytes(self):
        write_qls(self.path, [Frame([1, 0, 0, 0], -17, "x")], n=2)
        return bytearray(self.path.read_bytes())

    def test_exact_wire_encoding_and_round_trip(self):
        values = [complex(1, -2), complex(2**-24, -0.0), complex(65504, -65504), 0j]
        frames = [Frame(values, -(2**31), "π"), Frame([0j] * 4, 2**31 - 1, "")]
        write_qls(self.path, frames, n=2)
        expected = struct.pack("<4sHHIIIIII", b"QLS\0", 1, 0, 2, 2, 20, 0, 0, 0)
        expected += struct.pack("<iI", -(2**31), 2) + "π".encode() + b"\0\0"
        expected += struct.pack("<iI", 2**31 - 1, 0)
        expected += bytes.fromhex("003c00c001000080ff7bfffb00000000")
        expected += bytes(16)
        self.assertEqual(self.path.read_bytes(), expected)
        with Recording(self.path) as recording:
            self.assertEqual((recording.n, len(recording)), (2, 2))
            second = recording.read_frame(1)  # Exercise seeking out of order.
            first = recording.read_frame(0)
            self.assertEqual((second.timestamp_ms, second.title, second.amplitudes), (2**31 - 1, "", [0j] * 4))
            self.assertEqual((first.timestamp_ms, first.title, first.amplitudes), (-(2**31), "π", values))
            self.assertEqual(math.copysign(1, first.amplitudes[1].imag), -1)
            for index in [-1, 2]:
                with self.assertRaises(IndexError):
                    recording.read_frame(index)

    def test_float16_rounding_and_underflow_are_not_normalization(self):
        write_qls(self.path, [Frame([1 + 2**-11, 2**-25, 3 + 4j, -2**-24])], n=2)
        with Recording(self.path) as recording:
            self.assertEqual(recording.read_frame(0).amplitudes, [1, 0, 3 + 4j, -2**-24])

    def test_timestamp_order_is_not_restricted(self):
        write_qls(self.path, (Frame([1], t, "\ufefftitle") for t in [100, 100, -50, 0]), n=0)
        with Recording(self.path) as recording:
            self.assertEqual(recording.frames, [(t, "\ufefftitle") for t in [100, 100, -50, 0]])

    def test_writer_consumes_each_frame_before_requesting_the_next(self):
        def frames():
            state = [0j] * 4
            for index in range(4):
                state[index] = 1
                yield Frame(state, index, str(index))
        write_qls(self.path, frames(), n=2)
        with Recording(self.path) as recording:
            for index in range(4):
                self.assertEqual(recording.read_frame(index).amplitudes, [1] * (index + 1) + [0] * (3 - index))

    def test_invalid_write_preserves_existing_file_and_cleans_up(self):
        invalid = [
            ([], 2), ([Frame([0] * 4)], 1), ([Frame([0] * 4)], 22),
            ([Frame([0] * 3)], 2), ([Frame([0] * 4 + [None])], 2),
            ([Frame([0] * 4, 2**31)], 2), ([Frame([0] * 4, -(2**31) - 1)], 2),
            ([Frame([0] * 4, 1.5)], 2), ([Frame([0] * 4, 0, "π" * 513)], 2),
            ([Frame([float("nan")] * 4)], 2), ([Frame([float("inf")] * 4)], 2),
            ([Frame([65505] * 4)], 2), ([Frame([complex(0, -65505)] * 4)], 2),
        ]
        for frames, n in invalid:
            with self.subTest(frames=frames, n=n):
                self.path.write_bytes(b"keep me")
                with self.assertRaises((ValueError, TypeError)):
                    write_qls(self.path, frames, n=n)
                self.assertEqual(self.path.read_bytes(), b"keep me")
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        with patch("qls.os.replace", side_effect=OSError("cannot replace")):
            with self.assertRaises(OSError):
                write_qls(self.path, [Frame([1])], n=0)
        self.assertEqual(self.path.read_bytes(), b"keep me")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_writer_frame_and_index_limits(self):
        for limit, value in [("MAX_FRAMES", 1), ("MAX_INDEX_BYTES", 8)]:
            with self.subTest(limit=limit), patch.object(qls, limit, value):
                with self.assertRaises(ValueError):
                    write_qls(self.path, [Frame([1]), Frame([1])], n=0)

    def test_header_validation(self):
        original = self.valid_bytes()
        for offset, fmt, value in [(0, "<I", 0), (4, "<H", 2), (6, "<H", 1),
                                    (8, "<I", 3), (8, "<I", 22), (12, "<I", 0),
                                    (12, "<I", 100_001), (16, "<I", 7),
                                    (16, "<I", 16 * 1024 * 1024 + 1),
                                    (20, "<I", 1), (24, "<I", 1), (28, "<I", 1)]:
            with self.subTest(offset=offset, value=value):
                data = original.copy()
                struct.pack_into(fmt, data, offset, value)
                self.path.write_bytes(data)
                with self.assertRaises(ValueError):
                    Recording(self.path)

    def test_truncation_trailing_data_and_bad_titles(self):
        original = self.valid_bytes()
        invalid = [original[:20], original[:-1], original + b"\0"]
        for offset, value in [(36, 255), (40, 255), (41, 1)]:
            data = original.copy()
            data[offset] = value
            invalid.append(data)
        data = original.copy()
        struct.pack_into("<I", data, 16, 16)
        data[44:44] = bytes(4)  # Extra index bytes, but correct total file size.
        invalid.append(data)
        for data in invalid:
            with self.subTest(data=data):
                self.path.write_bytes(data)
                with self.assertRaises(ValueError):
                    Recording(self.path)

    def test_nonfinite_components_rejected_when_frame_is_read(self):
        original = self.valid_bytes()
        for bits in [0x7C00, 0xFC00, 0x7E00]:
            for offset in [44, 46]:
                with self.subTest(bits=bits, offset=offset):
                    data = original.copy()
                    struct.pack_into("<H", data, offset, bits)
                    self.path.write_bytes(data)
                    with Recording(self.path) as recording:
                        with self.assertRaises(ValueError):
                            recording.read_frame(0)

    def test_n20_frame(self):
        write_qls(self.path, [Frame((1j if k == 2**20 - 1 else 0 for k in range(2**20)))], n=20)
        self.assertEqual(self.path.stat().st_size, 32 + 8 + 4 * 2**20)
        with Recording(self.path) as recording:
            values = recording.read_frame(0).amplitudes
            self.assertEqual((len(values), values[0], values[-1]), (2**20, 0, 1j))

    def test_bundled_examples(self):
        directory = Path(__file__).resolve().parents[1] / "examples"
        expected = {"circuit-history.qls": (8, 10), "phase-sweep.qls": (12, 24), "sparsity.qls": (12, 12)}
        for name, shape in expected.items():
            with self.subTest(name=name), Recording(directory / name) as recording:
                self.assertEqual((recording.n, len(recording)), shape)
                for i in range(len(recording)):
                    frame = recording.read_frame(i)
                    self.assertTrue(frame.title)
                    self.assertEqual(len(frame.amplitudes), 2**recording.n)
                    if name == "circuit-history.qls":
                        self.assertAlmostEqual(sum(abs(v)**2 for v in frame.amplitudes), 1, delta=0.001)


if __name__ == "__main__":
    unittest.main()
