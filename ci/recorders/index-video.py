#!/usr/bin/env python3
"""Extract timestamped video frames and correlate them with native events."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import shutil
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
import zlib


def command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, capture_output=True, text=True, timeout=300, check=False)


def read_json_lines(path: Path) -> list[dict]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in rows if isinstance(row, dict)]


def screens_for_environment(path: Path) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = value.get("s01Displays", []) if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def display_mapping(content_rect: object, displays: list[dict]) -> dict | None:
    if not isinstance(content_rect, list) or len(content_rect) != 4:
        return None
    try:
        left, bottom, width, height = (float(value) for value in content_rect)
    except (TypeError, ValueError):
        return None
    center_x, center_y = left + width / 2, bottom + height / 2
    for display in displays:
        frame = display.get("frameAppkit")
        pixels = display.get("pixelSize")
        if not isinstance(frame, list) or len(frame) != 4 or not isinstance(pixels, list) or len(pixels) != 2:
            continue
        try:
            x, y, display_width, display_height = (float(value) for value in frame)
            pixel_width, pixel_height = (int(value) for value in pixels)
        except (TypeError, ValueError):
            continue
        if x <= center_x <= x + display_width and y <= center_y <= y + display_height:
            return {
                "displayFrameAppkit": frame,
                "displayPixelSize": [pixel_width, pixel_height],
                "windowContentRectAppkit": content_rect,
                "backingScaleFactor": display.get("backingScaleFactor"),
                "displayId": display.get("displayId"),
            }
    return None


def read_png_rgb(path: Path) -> tuple[int, int, bytes] | None:
    """Decode 8-bit RGB/RGBA PNG pixels using only the standard library."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    width = height = bit_depth = color_type = None
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            return None
        payload = data[start:end]
        if kind == b"IHDR" and len(payload) == 13:
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if compression or filtering or interlace:
                return None
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
        offset = end + 4
    if width is None or height is None or bit_depth != 8 or color_type not in {2, 6}:
        return None
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    try:
        raw = zlib.decompress(compressed)
    except zlib.error:
        return None
    if len(raw) != height * (stride + 1):
        return None
    pixels = bytearray(height * stride)
    cursor = 0
    for y in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row_start = y * stride
        previous_start = row_start - stride
        for x in range(stride):
            value = raw[cursor + x]
            left = pixels[row_start + x - channels] if x >= channels else 0
            above = pixels[previous_start + x] if y else 0
            upper_left = pixels[previous_start + x - channels] if y and x >= channels else 0
            if filter_type == 1:
                value += left
            elif filter_type == 2:
                value += above
            elif filter_type == 3:
                value += (left + above) // 2
            elif filter_type == 4:
                predictor = left + above - upper_left
                left_distance = abs(predictor - left)
                above_distance = abs(predictor - above)
                diagonal_distance = abs(predictor - upper_left)
                value += left if left_distance <= above_distance and left_distance <= diagonal_distance else above if above_distance <= diagonal_distance else upper_left
            elif filter_type != 0:
                return None
            pixels[row_start + x] = value & 0xFF
        cursor += stride
    return width, height, bytes(pixels)


def decode_s01_marker(image: Path, row: dict) -> tuple[int, int] | None:
    """Read the visible 24-bit sequence and 2-bit phase marker from a frame."""
    rect = row.get("windowContentRectAppkit")
    display = row.get("displayFrameAppkit")
    pixel_size = row.get("displayPixelSize")
    if not (isinstance(rect, list) and len(rect) == 4
            and isinstance(display, list) and len(display) == 4
            and isinstance(pixel_size, list) and len(pixel_size) == 2):
        return None
    try:
        left, bottom, content_width, content_height = [float(value) for value in rect]
        display_left, display_bottom, display_width, display_height = [float(value) for value in display]
        pixel_width, pixel_height = [int(value) for value in pixel_size]
    except (TypeError, ValueError):
        return None
    decoded = read_png_rgb(image)
    if decoded is None:
        return None
    image_width, image_height, pixels = decoded
    # A whole-display capture must match the measured display pixels exactly;
    # cropped or multi-display frames do not have a proven coordinate origin.
    if image_width != pixel_width or image_height != pixel_height or min(display_width, display_height, content_width, content_height) <= 0:
        return None
    scale_x = pixel_width / display_width
    scale_y = pixel_height / display_height
    content_left_px = (left - display_left) * scale_x
    content_top_px = (display_bottom + display_height - bottom - content_height) * scale_y
    code_left_px = content_left_px + (content_width - 139) * scale_x
    code_top_px = content_top_px + 24 * scale_y
    sequence = 0
    phase = 0
    for bit in range(26):
        x = int(round(code_left_px + (bit * 4 + 1.5) * scale_x))
        y = int(round(code_top_px + 4 * scale_y))
        if x < 0 or y < 0 or x >= image_width or y >= image_height:
            return None
        index = (y * image_width + x) * (4 if len(pixels) == image_width * image_height * 4 else 3)
        red, green, blue = pixels[index:index + 3]
        dark = red < 115 and green < 115 and blue < 115
        if bit < 24:
            sequence = (sequence << 1) | int(dark)
        else:
            phase = (phase << 1) | int(dark)
    return sequence, phase


def decode_presentation_marker(image: Path) -> tuple[int, int] | None:
    """Locate the chromatic sync word at any window position/backing scale."""
    decoded = read_png_rgb(image)
    if decoded is None:
        return None
    width, height, pixels = decoded
    channels = len(pixels) // (width * height)
    def color(x, y):
        offset = (y * width + x) * channels
        return pixels[offset:offset + 3]
    def magenta(rgb):
        return len(rgb) == 3 and rgb[0] > 180 and rgb[1] < 80 and rgb[2] > 180
    def cyan(rgb):
        return len(rgb) == 3 and rgb[0] < 80 and rgb[1] > 180 and rgb[2] > 180
    for y in range(4, height, 8):
        x = 0
        while x < width:
            if not magenta(color(x, y)):
                x += 2
                continue
            left = x
            while left > 0 and magenta(color(left - 1, y)):
                left -= 1
            end = x
            while end < width and magenta(color(end, y)):
                end += 1
            # Chroma subsampling can erode edges. Fit the full sync pattern.
            for cell in [end - left]:
                if left + 34 * cell >= width:
                    continue
                centers = [int(left + (bit + .5) * cell) for bit in range(34)]
                if not all((magenta if bit % 2 == 0 else cyan)(color(centers[bit], y)) for bit in range(8)):
                    continue
                bits = []
                for center in centers[8:]:
                    rgb = color(center, y)
                    if max(rgb) < 90:
                        bits.append(1)
                    elif min(rgb) > 165:
                        bits.append(0)
                    else:
                        break
                if len(bits) == 26:
                    value = 0
                    for bit in bits:
                        value = value * 2 + bit
                    return value >> 2, value & 3
            x = end + 1
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    video = args.video.resolve()
    index_path = evidence / "video/capture-index.jsonl"
    frame_dir = evidence / "screens/video-frames"
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not video.is_file() or not ffprobe or not ffmpeg:
        raise SystemExit("video or pinned ffmpeg tools are unavailable")

    probe = command([
        ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(video),
    ])
    if probe.returncode:
        raise SystemExit("ffprobe could not read the recording")
    try:
        probed = json.loads(probe.stdout).get("frames", [])
        pts = [Decimal(str(row["best_effort_timestamp_time"])) for row in probed if isinstance(row, dict) and row.get("best_effort_timestamp_time") is not None]
    except (json.JSONDecodeError, InvalidOperation, KeyError, TypeError):
        raise SystemExit("ffprobe returned invalid frame timestamps")
    if not pts:
        raise SystemExit("recording contains no timestamped video frames")

    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    extracted = command([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vsync", "0", "-pix_fmt", "rgb24", "-start_number", "1", str(frame_dir / "frame-%06d.png"),
    ])
    if extracted.returncode:
        raise SystemExit("ffmpeg could not extract timestamped frames")
    images = sorted(frame_dir.glob("frame-*.png"))
    if len(images) != len(pts):
        raise SystemExit("extracted frame count does not match ffprobe timestamps")

    try:
        clock = json.loads((evidence / "recorder/capture-clock.json").read_text(encoding="utf-8"))
        samples = clock.get("samples", []) if isinstance(clock, dict) else []
        start_sample = next((row for row in samples if isinstance(row, dict) and row.get("phase") == "start"), None)
        stop_sample = next((row for row in samples if isinstance(row, dict) and row.get("phase") == "stop"), None)
        uncertainty = int(clock.get("calibrationUncertaintyNanoseconds", 2**63 - 1))
        wall_to_monotonic = int(clock["wallToMonotonicOffsetNanoseconds"])
        clock_calibrated = (
            clock.get("status") == "measured"
            and start_sample is not None and stop_sample is not None
            and uncertainty <= 5_000_000
        )
        anchor = int(start_sample["monotonicNanoseconds"]) if start_sample else 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        clock = {"status": "UNVERIFIED", "reason": "paired recorder-lifetime clock samples are unavailable"}
        uncertainty = 2**63 - 1
        wall_to_monotonic = 0
        anchor = 0
        clock_calibrated = False
    native_events = read_json_lines(evidence / "recorder/s01-events.jsonl")
    native_events = sorted(
        (row for row in native_events if isinstance(row.get("monotonicNanoseconds"), int)),
        key=lambda row: row["monotonicNanoseconds"],
    )
    displays = screens_for_environment(evidence / "environment.json")
    try:
        environment = json.loads((evidence / "environment.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        environment = {}
    decode_s11 = environment.get("spike") == "s11"
    decode_s01 = isinstance(environment, dict) and environment.get("spike") == "s01" and environment.get("platform") == "macos"
    first_pts = pts[0]
    epoch_pts = first_pts >= Decimal(1_000_000_000)
    rows: list[dict] = []
    for number, (timestamp, image) in enumerate(zip(pts, images), 1):
        pts_offset_ns = int((timestamp - first_pts) * Decimal(1_000_000_000))
        if epoch_pts and clock_calibrated:
            frame_timestamp = int(timestamp * Decimal(1_000_000_000)) + wall_to_monotonic
            clock_mapping = "paired-realtime-monotonic"
        else:
            # Keep frame ordering usable for review while making no host-clock claim.
            frame_timestamp = anchor + pts_offset_ns
            clock_mapping = "UNVERIFIED: stream-relative PTS has no measured host-time origin"
        preceding = next((row for row in reversed(native_events) if row["monotonicNanoseconds"] <= frame_timestamp), None)
        native = preceding.get("native", {}) if preceding else {}
        mapping = display_mapping(native.get("contentRectOnScreenAppkit"), displays) if isinstance(native, dict) else None
        row = {
            "frameNumber": number,
            "timestampNanoseconds": frame_timestamp,
            "presentationTimestampNanoseconds": int(timestamp * Decimal(1_000_000_000)),
            "timestampSource": "ffprobe per-frame presentation timestamp",
            "clockMapping": clock_mapping,
            "relativePath": image.relative_to(evidence).as_posix(),
        }
        if mapping:
            row.update(mapping)
        if decode_s01 or decode_s11:
            visible = decode_presentation_marker(image) if decode_s11 else decode_s01_marker(image, row)
            if visible is not None:
                row["visibleSequence"], row["visiblePhaseBits"] = visible
                row["visiblePhase"] = "tokens-mutated" if decode_s11 and visible[1] == 2 else {0: "ready", 1: "applying", 2: "settled", 3: "error"}[visible[1]]
                row["visibleSequenceStatus"] = "decoded"
            else:
                row["visibleSequenceStatus"] = "UNVERIFIED"
        rows.append(row)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")

    renderer_events = read_json_lines(evidence / "recorder/renderer-events.jsonl")
    links_path = evidence / "recorder/presentation-links.jsonl"
    refresh_hz = None
    try:
        environment = json.loads((evidence / "environment.json").read_text(encoding="utf-8"))
        display = environment.get("display", {}) if isinstance(environment, dict) else {}
        refresh_hz = float(display.get("refreshHz")) if isinstance(display, dict) and display.get("refreshHz") is not None else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        refresh_hz = None
    refresh_interval_ns = int(1_000_000_000 / refresh_hz) if refresh_hz and refresh_hz > 0 else None
    frame_correlations: list[bool] = []
    with links_path.open("w", encoding="utf-8") as stream:
        if not renderer_events:
            stream.write(json.dumps({"status": "UNVERIFIED", "reason": "renderer event transport produced no records"}) + "\n")
        for event in renderer_events:
            receipt_time = event.get("hostReceiptMonotonicNanoseconds", event.get("hostMonotonicNanoseconds"))
            update_time = event.get("hostUpdateMonotonicNanoseconds")
            detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
            sequence = detail.get("sequence") if event.get("type") == "shell-spike:frame" else None
            expected_phase = detail.get("phase")
            if decode_s11 and (expected_phase != "tokens-mutated" or not sequence):
                continue
            if decode_s01 and (expected_phase != "settled" or not sequence):
                continue
            # First matching paint, even if it predates the claimed update: never
            # skip an early frame and choose a later one to manufacture a join.
            next_frame = next((row for row in rows if sequence is not None
                               and row.get("visibleSequence") == sequence
                               and (expected_phase is None or row.get("visiblePhase") == expected_phase)), None)
            previous = rows[next_frame["frameNumber"] - 2] if next_frame and next_frame["frameNumber"] > 1 else None
            first_change = bool(previous and previous.get("visibleSequenceStatus") == "decoded"
                                and (previous.get("visibleSequence"), previous.get("visiblePhase"))
                                != (sequence, expected_phase))
            delay = next_frame["timestampNanoseconds"] - update_time if next_frame and isinstance(update_time, int) else None
            native_delay = next_frame["timestampNanoseconds"] - receipt_time if next_frame and isinstance(receipt_time, int) else None
            matched = (
                next_frame is not None and isinstance(receipt_time, int) and isinstance(update_time, int)
                and 0 < receipt_time <= update_time and clock_calibrated and epoch_pts
                and refresh_interval_ns is not None and delay is not None
                and first_change and 0 <= delay and native_delay is not None
                and 0 <= native_delay and native_delay + uncertainty <= refresh_interval_ns
            )
            if sequence is not None:
                frame_correlations.append(matched)
            measured_late = (next_frame is not None and first_change and isinstance(receipt_time, int)
                             and isinstance(update_time, int) and 0 < receipt_time <= update_time
                             and clock_calibrated and epoch_pts and refresh_interval_ns is not None
                             and delay is not None and delay >= 0 and native_delay is not None
                             and native_delay + uncertainty > refresh_interval_ns)
            link = {
                "eventType": event.get("type"),
                "sequence": sequence,
                "nativeReceiptMonotonicNanoseconds": receipt_time,
                "hostUpdateMonotonicNanoseconds": update_time,
                "frameNumber": next_frame.get("frameNumber") if next_frame else None,
                "frameRelativePath": next_frame.get("relativePath") if next_frame else None,
                "eventToFrameNanoseconds": native_delay,
                "hostUpdateToFrameNanoseconds": delay,
                "measuredRefreshIntervalNanoseconds": refresh_interval_ns,
                "clockCalibrationUncertaintyNanoseconds": uncertainty,
                "status": "correlated" if matched else "measured-late" if measured_late else "UNVERIFIED",
            }
            if sequence is not None and next_frame is None:
                link["reason"] = "visible sequence decoder did not identify a matching captured frame"
            elif not isinstance(receipt_time, int) or not isinstance(update_time, int):
                link["reason"] = "native receipt and host update timestamps are both required for a calibrated join"
            elif update_time < receipt_time:
                link["reason"] = "host update timestamp precedes native receipt"
            elif not clock_calibrated or not epoch_pts:
                link["reason"] = "capture timestamps are not calibrated to the host monotonic event clock"
            elif refresh_interval_ns is None:
                link["reason"] = "display refresh interval was not measured"
            elif native_delay is not None and native_delay + uncertainty > refresh_interval_ns:
                link["reason"] = "event-to-presentation delay exceeded one measured refresh interval"
            stream.write(json.dumps(link, separators=(",", ":")) + "\n")
    sequence_correlation_measured = bool(frame_correlations) and all(frame_correlations)
    (evidence / "recorder/capture-index-status.json").write_text(json.dumps({
        "status": "indexed" if rows else "UNVERIFIED",
        "sequenceCorrelationStatus": "measured" if sequence_correlation_measured else "UNVERIFIED",
        "sequenceDecoder": "self-locating-s11-24-bit-sequence-plus-2-bit-phase" if decode_s11 else "s01-visible-24-bit-sequence-plus-2-bit-phase" if decode_s01 else "not-applicable-to-this-case",
        "frameCount": len(rows),
        "clock": clock,
        "clockCalibrated": clock_calibrated and epoch_pts,
        "clockCalibrationUncertaintyNanoseconds": uncertainty,
        "mappingRows": sum("displayFrameAppkit" in row for row in rows),
        "video": video.relative_to(evidence).as_posix(),
        "videoSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
