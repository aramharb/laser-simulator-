import cv2
import numpy as np
import asyncio
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from configurator import Configurator
from projector_calibrator import ProjectorCalibrator
import configurator as config_keys
from shot_detector import JavaShotDetector

app = FastAPI()

CALIBRATION_TIMEOUT_SECONDS = 8.0
SHOT_LUMINANCE_MODE = "combined"
SHOT_BRIGHTNESS_INCREASE_RATIO = 0.10
SHOT_EXCESSIVE_BRIGHTNESS_RATIO = 0.96
SHOT_MIN_DIMENSION = 8
SHOT_DYNAMIC_RATIO_CAP = 0.25
SHOT_USE_DYNAMIC_THRESHOLD = True
SHOT_USE_EXCESSIVE_MASK = True
SHOT_USE_VARIANCE_THRESHOLD = True
SHOT_VARIANCE_ALPHA = 0.05
SHOT_VARIANCE_K = 2.5
SHOT_USE_TEMPORAL_FILTER = True
SHOT_TEMPORAL_WINDOW = 3
SHOT_TEMPORAL_MIN_FRAMES = 1
DEBUG_FRAME_STATS = True
BLACK_FRAME_STREAK_LIMIT = 15
DEBUG_PREVIEW_ENABLED = False
DEBUG_PREVIEW_SECONDS = 4.0
DEBUG_PREVIEW_SQUARE_RATIO = 0.35
DEBUG_PREVIEW_WINDOW = "ShootOFF Debug Preview"
DEBUG_BBOX_PREVIEW_SECONDS = 6.0


def open_capture(source):
    if isinstance(source, int):
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap

    cap = cv2.VideoCapture(source)
    if cap.isOpened():
        return cap

    try:
        return cv2.VideoCapture(source, cv2.CAP_MSMF)
    except Exception:
        return cap


def normalize_bbox(bbox):
    x1, y1, x2, y2 = [int(value) for value in bbox]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return left, top, right, bottom


def is_valid_bbox(bbox):
    left, top, right, bottom = bbox
    return right > left and bottom > top


def build_roi_mask(width, height, bbox):
    mask = np.zeros((height, width), dtype=np.uint8)
    left, top, right, bottom = bbox
    mask[top:bottom + 1, left:right + 1] = 255
    return mask


def draw_center_square(frame, ratio, color=(255, 255, 255), thickness=2):
    height, width = frame.shape[:2]
    size = max(1, int(min(width, height) * ratio))
    half = size // 2
    cx, cy = width // 2, height // 2
    x1 = max(cx - half, 0)
    y1 = max(cy - half, 0)
    x2 = min(cx + half, width - 1)
    y2 = min(cy + half, height - 1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)


def draw_bbox(frame, bbox, color=(0, 255, 255), thickness=2):
    left, top, right, bottom = bbox
    cv2.rectangle(frame, (left, top), (right, bottom), color, thickness)


def parse_bool_param(value):
    if value is None:
        return None

    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return None


def get_capture_fps(cap, default=30.0):
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
    except Exception:
        return default

    if fps <= 0 or not np.isfinite(fps):
        return default
    return fps


def should_ignore_shot_color(shot_color, ignore_color):
    ignore_color = str(ignore_color).strip().lower()
    if ignore_color == "none":
        return False
    return ignore_color in str(shot_color).strip().lower()

class ShootOffAPI:
    def __init__(self, config=None, prefs=None, calibrator=None, detector_factory=None, argv=None):
        self.config = config if config is not None else Configurator(argv=[] if argv is None else argv)
        self.prefs = prefs if prefs is not None else self.config.get_preferences()
        self.calibrator = calibrator if calibrator is not None else ProjectorCalibrator()
        self.detector_factory = detector_factory if detector_factory is not None else self._build_detector
        self.cap = None
        self.active_bbox = None
        self.calibration_confidence = 0.0
        self._shot_brightness_ratio = self._intensity_to_ratio(
            self.prefs.get(config_keys.LASER_INTENSITY)
        )

    def reset_calibration(self):
        self.active_bbox = None
        self.calibration_confidence = 0.0
        if hasattr(self.calibrator, "reset"):
            self.calibrator.reset()

    def _pref_bool(self, key, default):
        value = self.prefs.get(key, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "y", "on"):
            return True
        if text in ("false", "0", "no", "n", "off"):
            return False
        return default

    def _pref_int(self, key, default):
        value = self.prefs.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _pref_float(self, key, default):
        value = self.prefs.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _pref_str(self, key, default):
        value = self.prefs.get(key, default)
        text = str(value).strip() if value is not None else ""
        return text if text else default

    def _intensity_to_ratio(self, intensity):
        if intensity is None:
            return SHOT_BRIGHTNESS_INCREASE_RATIO
        try:
            value = int(intensity)
        except (TypeError, ValueError):
            return SHOT_BRIGHTNESS_INCREASE_RATIO
        if value <= 0:
            return SHOT_BRIGHTNESS_INCREASE_RATIO
        return float(value) / 255.0

    @staticmethod
    def _shot_within_bbox(raw_x, raw_y, bbox):
        # Inclusive check: shots landing exactly on the calibration boundary
        # (very common at the edge of a target) must not be silently dropped.
        return (
            raw_x >= bbox[0]
            and raw_x <= bbox[2]
            and raw_y >= bbox[1]
            and raw_y <= bbox[3]
        )

    def _build_detector(self, width, height):
        brightness_ratio = self._intensity_to_ratio(
            self.prefs.get(config_keys.LASER_INTENSITY)
        )
        self._shot_brightness_ratio = brightness_ratio

        return JavaShotDetector(
            width,
            height,
            luminance_mode=self._pref_str(
                config_keys.SHOT_LUMINANCE_MODE,
                SHOT_LUMINANCE_MODE,
            ),
            brightness_increase_ratio=brightness_ratio,
            excessive_brightness_ratio=self._pref_float(
                config_keys.SHOT_EXCESSIVE_BRIGHTNESS_RATIO,
                SHOT_EXCESSIVE_BRIGHTNESS_RATIO,
            ),
            min_shot_dimension=self._pref_int(
                config_keys.SHOT_MIN_DIMENSION,
                SHOT_MIN_DIMENSION,
            ),
            max_dynamic_ratio=self._pref_float(
                config_keys.SHOT_DYNAMIC_RATIO_CAP,
                SHOT_DYNAMIC_RATIO_CAP,
            ),
            use_dynamic_threshold=self._pref_bool(
                config_keys.SHOT_USE_DYNAMIC_THRESHOLD,
                SHOT_USE_DYNAMIC_THRESHOLD,
            ),
            use_variance_threshold=self._pref_bool(
                config_keys.SHOT_USE_VARIANCE_THRESHOLD,
                SHOT_USE_VARIANCE_THRESHOLD,
            ),
            variance_alpha=self._pref_float(
                config_keys.SHOT_VARIANCE_ALPHA,
                SHOT_VARIANCE_ALPHA,
            ),
            variance_k=self._pref_float(
                config_keys.SHOT_VARIANCE_K,
                SHOT_VARIANCE_K,
            ),
            use_temporal_filter=self._pref_bool(
                config_keys.SHOT_USE_TEMPORAL_FILTER,
                SHOT_USE_TEMPORAL_FILTER,
            ),
            temporal_window=self._pref_int(
                config_keys.SHOT_TEMPORAL_WINDOW,
                SHOT_TEMPORAL_WINDOW,
            ),
            temporal_min_frames=self._pref_int(
                config_keys.SHOT_TEMPORAL_MIN_FRAMES,
                SHOT_TEMPORAL_MIN_FRAMES,
            ),
            use_excessive_mask=self._pref_bool(
                config_keys.SHOT_USE_EXCESSIVE_MASK,
                SHOT_USE_EXCESSIVE_MASK,
            ),
        )

    def _build_shot_candidate(
        self,
        shot,
        bbox,
        ignore_color,
    ):
        shot_color = str(shot.get("color", "")).lower()
        if should_ignore_shot_color(shot_color, ignore_color):
            return None

        raw_x = float(shot.get("x", 0.0) or 0.0)
        raw_y = float(shot.get("y", 0.0) or 0.0)
        if not np.isfinite(raw_x) or not np.isfinite(raw_y):
            return None

        if not self._shot_within_bbox(raw_x, raw_y, bbox):
            return None

        confidence = float(shot.get("confidence", 0.0) or 0.0)
        if not np.isfinite(confidence):
            confidence = 0.0

        return {
            "raw_x": raw_x,
            "raw_y": raw_y,
            "color": shot_color,
            "confidence": round(confidence, 3),
        }

    def _map_shot_to_arena(
        self,
        raw_x: float,
        raw_y: float,
        bbox,
        arena_w: int,
        arena_h: int,
    ) -> tuple[float, float]:
        bbox_width = float(bbox[2] - bbox[0])
        bbox_height = float(bbox[3] - bbox[1])

        if bbox_width < 10.0 or bbox_height < 10.0:
            print(
                "SHOT_DEBUG warning=invalid_bbox bbox={} width={:.2f} height={:.2f}".format(
                    bbox,
                    bbox_width,
                    bbox_height,
                )
            )
            return 0.0, 0.0

        x_scale = float(arena_w) / bbox_width
        y_scale = float(arena_h) / bbox_height

        calibrated_x = (raw_x - bbox[0]) * x_scale
        calibrated_y = (raw_y - bbox[1]) * y_scale

        # Keep mapped shots inside the arena bounds.
        arena_max_x = max(float(arena_w), 0.0)
        arena_max_y = max(float(arena_h), 0.0)

        return (
            float(np.clip(calibrated_x, 0.0, arena_max_x)),
            float(np.clip(calibrated_y, 0.0, arena_max_y)),
        )

    async def _send_calibration_status(
        self,
        websocket: WebSocket,
        status: str,
        *,
        bbox=None,
        mode=None,
        reason=None,
        confidence=None,
        elapsed_seconds=None,
        arena_w=None,
        arena_h=None,
    ):
        payload = {"status": status}

        if bbox is not None:
            payload["bbox"] = list(bbox)
        if mode is not None:
            payload["mode"] = mode
        if reason is not None:
            payload["reason"] = reason
        if confidence is not None:
            payload["confidence"] = round(float(confidence), 3)
        if elapsed_seconds is not None:
            payload["elapsed_seconds"] = round(float(elapsed_seconds), 2)
        if arena_w is not None:
            payload["arena_w"] = arena_w
        if arena_h is not None:
            payload["arena_h"] = arena_h

        await websocket.send_json(payload)

    async def run_session(
        self,
        websocket: WebSocket,
        debug_preview=None,
        force_calibration=False,
        bbox_preview=None,
    ):
        if force_calibration:
            self.reset_calibration()

        cap = open_capture(self.prefs[config_keys.VIDCAM])

        if not cap.isOpened():
            await websocket.send_json({"error": "Webcam not found"})
            cap.release()
            return

        capture_fps = get_capture_fps(cap)
        active_bbox = self.active_bbox if self.active_bbox is not None and is_valid_bbox(self.active_bbox) else None
        calibration_locked = active_bbox is not None
        calibration_start = time.monotonic()

        # Arena dimensions: the client sends its actual canvas size as query
        # parameters (?arena_w=1280&arena_h=720).  Fall back to 800×600 only
        # when neither parameter is present so legacy clients still work.
        # A mismatch between arena_w/h and the frontend canvas causes every
        # shot coordinate to be linearly offset — the single most common
        # calibration complaint.
        try:
            arena_w = int(websocket.query_params.get("arena_w"))
            arena_h = int(websocket.query_params.get("arena_h"))
            if arena_w < 1 or arena_h < 1:
                raise ValueError
        except (TypeError, ValueError):
            await websocket.send_json({"error": "Missing or invalid arena_w/arena_h"})
            cap.release()
            return
        last_shot_time = 0.0
        min_shot_interval = 0.15
        detector = None
        detector_frame_shape = None
        detector_intensity = None
        detector_roi_bbox = None
        ignore_color = str(self.prefs.get(config_keys.IGNORE_LASER_COLOR, "none")).lower()
        last_debug_log = 0.0
        debug_interval = 1.0
        black_frame_streak = 0
        debug_preview_until = None
        debug_window_open = False
        debug_preview_enabled = DEBUG_PREVIEW_ENABLED if debug_preview is None else debug_preview
        bbox_preview_enabled = False if bbox_preview is None else bbox_preview
        preview_enabled = debug_preview_enabled or bbox_preview_enabled

        if preview_enabled:
            debug_preview_until = time.monotonic() + DEBUG_PREVIEW_SECONDS

        if calibration_locked:
            await self._send_calibration_status(
                websocket,
                "calibrated",
                bbox=active_bbox,
                mode="cached",
                confidence=self.calibration_confidence,
                elapsed_seconds=0.0,
                arena_w=arena_w,
                arena_h=arena_h,
            )
            if preview_enabled:
                debug_preview_until = time.monotonic() + DEBUG_BBOX_PREVIEW_SECONDS

        last_frame_shape = None

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_shape = frame.shape[:2]
                if last_frame_shape is None:
                    last_frame_shape = frame_shape
                elif frame_shape != last_frame_shape:
                    print(
                        "SHOT_DEBUG warning=frame_shape_changed from={} to={}".format(
                            last_frame_shape,
                            frame_shape,
                        )
                    )
                    self.reset_calibration()
                    active_bbox = None
                    calibration_locked = False
                    calibration_start = time.monotonic()
                    last_frame_shape = frame_shape

                frame_max = int(np.max(frame)) if frame is not None and frame.size else 0
                if frame_max == 0:
                    black_frame_streak += 1
                    if black_frame_streak >= BLACK_FRAME_STREAK_LIMIT:
                        print("SHOT_DEBUG warning=black_frames reopening_camera")
                        cap.release()
                        cap = open_capture(self.prefs[config_keys.VIDCAM])
                        capture_fps = get_capture_fps(cap)
                        black_frame_streak = 0
                    await asyncio.sleep(self.prefs[config_keys.DETECTION_RATE] / 1000.0)
                    continue
                else:
                    black_frame_streak = 0

                if preview_enabled and debug_preview_until is not None:
                    now_preview = time.monotonic()
                    if now_preview <= debug_preview_until:
                        preview = frame.copy()
                        draw_center_square(preview, DEBUG_PREVIEW_SQUARE_RATIO)
                        result = self.calibrator.get_result()
                        preview_bbox = None
                        if result.valid:
                            preview_bbox = normalize_bbox(result.as_bbox())
                        elif active_bbox is not None and is_valid_bbox(active_bbox):
                            preview_bbox = active_bbox
                        if preview_bbox is not None and is_valid_bbox(preview_bbox):
                            draw_bbox(preview, preview_bbox)
                        try:
                            if not debug_window_open:
                                cv2.namedWindow(DEBUG_PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
                                debug_window_open = True
                            cv2.imshow(DEBUG_PREVIEW_WINDOW, preview)
                            cv2.waitKey(1)
                        except Exception:
                            preview_enabled = False
                            if debug_window_open:
                                cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                                debug_window_open = False
                                debug_preview_until = None
                    else:
                        if debug_window_open:
                            cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                            debug_window_open = False
                        debug_preview_until = None

                frame_height, frame_width = frame.shape[:2]
                laser_intensity = self.prefs.get(config_keys.LASER_INTENSITY)

                if (detector is None
                    or detector_frame_shape != (frame_width, frame_height)
                    or detector_intensity != laser_intensity):
                    detector = self.detector_factory(frame_width, frame_height)
                    detector_frame_shape = (frame_width, frame_height)
                    detector_intensity = laser_intensity
                    detector_roi_bbox = None

                # 1. Calibration Phase
                if not calibration_locked:
                    self.calibrator.calibrate_projector(frame)
                    result = self.calibrator.get_result()
                    elapsed_seconds = time.monotonic() - calibration_start

                    if result.valid:
                        normalized_bbox = normalize_bbox(result.as_bbox())
                        if is_valid_bbox(normalized_bbox):
                            calibration_locked = True
                            active_bbox = normalized_bbox
                            self.active_bbox = normalized_bbox
                            self.calibration_confidence = float(result.confidence)
                            await self._send_calibration_status(
                                websocket,
                                "calibrated",
                                bbox=normalized_bbox,
                                mode="auto",
                                confidence=result.confidence,
                                elapsed_seconds=elapsed_seconds,
                                arena_w=arena_w,
                                arena_h=arena_h,
                            )
                            if preview_enabled:
                                debug_preview_until = time.monotonic() + DEBUG_BBOX_PREVIEW_SECONDS
                        else:
                            await self._send_calibration_status(
                                websocket,
                                "calibrating",
                                elapsed_seconds=elapsed_seconds,
                            )
                            await asyncio.sleep(0.1)
                            continue
                    else:
                        if elapsed_seconds >= CALIBRATION_TIMEOUT_SECONDS:
                            await self._send_calibration_status(
                                websocket,
                                "calibration_failed",
                                reason="timeout",
                                elapsed_seconds=elapsed_seconds,
                            )
                            return
                        await self._send_calibration_status(
                            websocket,
                            "calibrating",
                            elapsed_seconds=elapsed_seconds,
                        )
                        await asyncio.sleep(0.1)
                        continue

                # 2. Shot Detection Phase (Java shot detector port)
                if active_bbox is None:
                    result = self.calibrator.get_result()
                    if result.valid:
                        normalized_bbox = normalize_bbox(result.as_bbox())
                        if is_valid_bbox(normalized_bbox):
                            active_bbox = normalized_bbox

                if active_bbox is None or not is_valid_bbox(active_bbox):
                    await asyncio.sleep(self.prefs[config_keys.DETECTION_RATE] / 1000.0)
                    continue

                bbox = active_bbox
                frame_height, frame_width = frame.shape[:2]
                if DEBUG_FRAME_STATS:
                    if frame is None or frame.size == 0:
                        avg_pixel = 0.0
                        max_pixel = 0
                        shape_info = None
                        dtype_info = None
                    else:
                        avg_pixel = float(np.mean(frame))
                        max_pixel = int(np.max(frame))
                        shape_info = frame.shape
                        dtype_info = str(frame.dtype)
                else:
                    avg_pixel = 0.0
                    max_pixel = 0
                    shape_info = None
                    dtype_info = None

                if detector is not None and bbox is not None and is_valid_bbox(bbox):
                    if detector_roi_bbox != bbox:
                        detector.set_roi(build_roi_mask(frame_width, frame_height, bbox))
                        detector_roi_bbox = bbox

                shots = detector.process_frame(frame, fps=max(int(round(capture_fps)), 1))

                shot_candidates = []
                for shot in shots:
                    candidate = self._build_shot_candidate(shot, bbox, ignore_color)
                    if candidate is not None:
                        shot_candidates.append(candidate)

                now_debug = time.monotonic()
                if now_debug - last_debug_log >= debug_interval:
                    last_debug_log = now_debug
                    print(
                        "SHOT_DEBUG candidates={} clusters={} shots={} max_lum={} max_inc={} min_dim={} dyn_ratio={} excessive={} frame_shape={} dtype={} avg_px={:.2f} max_px={} bbox={}".format(
                            getattr(detector, "last_candidate_count", 0),
                            getattr(detector, "last_cluster_count", 0),
                            getattr(detector, "last_shot_count", 0),
                            getattr(detector, "last_max_lum", 0),
                            getattr(detector, "last_max_increase", 0),
                            getattr(detector, "MINIMUM_SHOT_DIMENSION", 0),
                            getattr(detector, "last_dynamic_ratio", 0.0),
                            getattr(detector, "last_excessive_count", 0),
                            shape_info,
                            dtype_info,
                            avg_pixel,
                            max_pixel,
                            bbox,
                        )
                    )

                if not shot_candidates:
                    await asyncio.sleep(self.prefs[config_keys.DETECTION_RATE] / 1000.0)
                    continue

                best_shot = max(shot_candidates, key=lambda candidate: candidate["confidence"])

                now = time.monotonic()
                if now - last_shot_time < min_shot_interval:
                    await asyncio.sleep(self.prefs[config_keys.DETECTION_RATE] / 1000.0)
                    continue

                last_shot_time = now
                calibrated_x, calibrated_y = self._map_shot_to_arena(
                    best_shot["raw_x"],
                    best_shot["raw_y"],
                    bbox,
                    arena_w,
                    arena_h,
                )

                await websocket.send_json({
                    "event": "shot",
                    "x": calibrated_x,
                    "y": calibrated_y,
                    "raw_x": best_shot["raw_x"],
                    "raw_y": best_shot["raw_y"],
                    "color": best_shot["color"],
                    "confidence": best_shot["confidence"],
                    "timestamp": cv2.getTickCount()
                })

                # Throttling to prevent CPU saturation, matching legacy DETECTION_RATE
                await asyncio.sleep(self.prefs[config_keys.DETECTION_RATE] / 1000.0)

        except WebSocketDisconnect:
            print("Angular app disconnected")
        finally:
            cap.release()
            if debug_window_open:
                cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)

shootoff_service = ShootOffAPI()

@app.websocket("/api/ws/shots")
@app.websocket("/ws/shots")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    debug_preview = parse_bool_param(websocket.query_params.get("debug"))
    bbox_preview = parse_bool_param(websocket.query_params.get("bbox_preview"))
    force_calibration = parse_bool_param(websocket.query_params.get("calibrate"))
    await shootoff_service.run_session(
        websocket,
        debug_preview=debug_preview,
        force_calibration=bool(force_calibration),
        bbox_preview=bbox_preview,
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)