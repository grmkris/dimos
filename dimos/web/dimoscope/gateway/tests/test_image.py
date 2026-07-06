#!/usr/bin/env python3
# Unit tests for the image plane (raw camera Image → <topic>_jpeg republish): transcode output,
# header/ts preservation, and the feedback guards. Drives _process directly — no event loop.
#
# Run: uv run pytest dimos/web/dimoscope/gateway/tests/test_image.py -q
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))  # dimoscope root → gateway pkg

np = pytest.importorskip("numpy")
pytest.importorskip("turbojpeg")
pytest.importorskip("dimos.msgs.sensor_msgs.Image")

from gateway.bus import Bus, Sample
from gateway.image import ImagePlane

from dimos.msgs.sensor_msgs.Image import Image, ImageFormat


def _raw_payload(w: int = 32, h: int = 16, ts: float = 1234.5) -> bytes:
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[:, : w // 2] = (255, 0, 0)  # left half red — a decodable, non-trivial pattern
    return Image(data=rgb, format=ImageFormat.RGB, frame_id="cam", ts=ts).lcm_encode()


def _plane_with_capture() -> tuple[ImagePlane, list]:
    bus = Bus()
    plane = ImagePlane(bus)
    assert plane.enabled  # importorskip above guarantees the deps
    out: list = []
    bus.republish = lambda topic, typ, payload: out.append((topic, typ, payload))  # type: ignore[method-assign]
    return plane, out


def test_raw_image_republished_as_jpeg_with_header_kept():
    plane, out = _plane_with_capture()
    plane._process("/color_image", _raw_payload(ts=1234.5))
    assert len(out) == 1
    topic, typ, payload = out[0]
    assert (topic, typ) == ("/color_image_jpeg", "sensor_msgs.Image")
    decoded = Image.lcm_decode(payload)  # encoding=jpeg → the jpeg decode path
    assert decoded.width == 32 and decoded.height == 16
    assert decoded.ts == pytest.approx(1234.5, abs=1e-6)  # source stamp preserved
    assert decoded.frame_id == "cam"
    assert len(payload) < len(_raw_payload())  # actually compressed


def test_already_jpeg_payload_is_skipped():
    plane, out = _plane_with_capture()
    jpeg_payload = Image(
        data=np.zeros((8, 8, 3), dtype=np.uint8), format=ImageFormat.RGB
    ).lcm_jpeg_encode()
    plane._process("/color_image", jpeg_payload)
    assert out == []  # never double-compress


def test_derived_topic_and_non_image_types_are_not_enqueued():
    plane, _ = _plane_with_capture()
    plane._on_sample(Sample("/color_image_jpeg", "sensor_msgs.Image", b"", _raw_payload()))
    plane._on_sample(Sample("/lidar", "sensor_msgs.PointCloud2", b"", b"x"))
    assert plane._in._latest == {}  # feedback + type guards keep the queue empty


def test_row_padded_stride_is_handled():
    # Many camera drivers pad rows (step > width*channels); the transcode must slice, not raise.
    from dimos_lcm.sensor_msgs.Image import Image as LCMImage
    from dimos_lcm.std_msgs.Header import Header

    w, h, ch, step = 4, 4, 3, 16  # 12 pixel bytes + 4 pad per row
    msg = LCMImage()
    msg.header = Header()
    msg.header.frame_id = "cam"
    msg.height, msg.width, msg.encoding, msg.is_bigendian, msg.step = h, w, "rgb8", False, step
    row = bytes([200, 50, 50] * w) + b"\x00" * (step - w * ch)
    msg.data = row * h
    msg.data_length = len(msg.data)

    plane, out = _plane_with_capture()
    plane._process("/padded", msg.lcm_encode())
    assert len(out) == 1
    decoded = Image.lcm_decode(out[0][2])
    assert decoded.width == w and decoded.height == h


def test_garbage_payload_never_raises():
    plane, out = _plane_with_capture()
    plane._process("/color_image", b"not an lcm message")
    assert out == []
