import asyncio
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import api as api_module
import configurator as config_keys
from projector_calibrator import CalibrationResult, ProjectorCalibrator
from shot_detector import JavaShotDetector


FRAME_WIDTH = 320
FRAME_HEIGHT = 240
CALIBRATION_WIDTH = 640
CALIBRATION_HEIGHT = 480


def make_frame(width, height, background=0):
    return np.full((height, width, 3), background, dtype=np.uint8)


def make_detector():
    return JavaShotDetector(
        FRAME_WIDTH,
        FRAME_HEIGHT,
        luminance_mode="combined",
        brightness_increase_ratio=0.10,
        excessive_brightness_ratio=0.96,
        min_shot_dimension=8,
        max_dynamic_ratio=0.25,
        use_dynamic_threshold=True,
        use_variance_threshold=True,
        variance_alpha=0.05,
        variance_k=2.5,
        use_temporal_filter=True,
        temporal_window=3,
        temporal_min_frames=1,
        use_excessive_mask=True,
    )


def draw_laser_square(frame, color=(255, 255, 255)):
    cv2.rectangle(frame, (150, 100), (154, 104), color, -1)
    return frame


def make_color_calibration_frame(rect_coords=(390, 355, 639, 479)):
    frame = make_frame(CALIBRATION_WIDTH, CALIBRATION_HEIGHT, background=0)
    triangle = np.array([[0, 0], [250, 0], [125, 250]], np.int32)
    cv2.fillPoly(frame, [triangle], (0, 255, 0))
    x1, y1, x2, y2 = rect_coords
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), -1)
    return frame


def make_gray_calibration_frame(rect_coords=(390, 355, 639, 479), value=120):
    frame = make_frame(CALIBRATION_WIDTH, CALIBRATION_HEIGHT, background=20)
    triangle = np.array([[0, 0], [250, 0], [125, 250]], np.int32)
    cv2.fillPoly(frame, [triangle], (value, value, value))
    x1, y1, x2, y2 = rect_coords
    cv2.rectangle(frame, (x1, y1), (x2, y2), (value, value, value), -1)
    return frame


class ShotDetectorTuningTests(unittest.TestCase):
    def test_static_glare_is_suppressed_after_warmup(self):
        detector = make_detector()
        glare = make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=0)
        cv2.rectangle(glare, (80, 60), (200, 180), (255, 255, 255), -1)

        for _ in range(8):
            self.assertEqual(detector.process_frame(glare), [])

    def test_small_laser_cluster_triggers_on_single_frame(self):
        detector = make_detector()
        background = make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=0)

        for _ in range(8):
            self.assertEqual(detector.process_frame(background), [])

        laser = make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=0)
        draw_laser_square(laser)

        shots = detector.process_frame(laser)

        self.assertEqual(len(shots), 1)
        shot = shots[0]
        self.assertEqual(shot["color"], "RED")
        self.assertIn("confidence", shot)
        self.assertGreater(shot["confidence"], 0.0)
        self.assertLessEqual(shot["confidence"], 1.0)
        self.assertAlmostEqual(shot["x"], 152.0, delta=2.5)
        self.assertAlmostEqual(shot["y"], 102.0, delta=2.5)


class ProjectorCalibratorTests(unittest.TestCase):
    def test_color_quadrant_lock_succeeds(self):
        calibrator = ProjectorCalibrator()
        frame = make_color_calibration_frame()

        for _ in range(4):
            calibrator.calibrate_projector(frame)

        result = calibrator.get_result()
        self.assertTrue(result.valid)
        self.assertGreater(result.confidence, 0.5)
        self.assertLessEqual(result.top_x, 10)
        self.assertLessEqual(result.top_y, 10)
        self.assertGreaterEqual(result.bottom_x, CALIBRATION_WIDTH - 10)
        self.assertGreaterEqual(result.bottom_y, CALIBRATION_HEIGHT - 10)

    def test_corner_touching_markers_snap_to_frame_edges(self):
        calibrator = ProjectorCalibrator()
        frame = make_color_calibration_frame()

        for _ in range(4):
            calibrator.calibrate_projector(frame)

        result = calibrator.get_result()
        self.assertTrue(result.valid)
        self.assertEqual(result.top_x, 0)
        self.assertEqual(result.top_y, 0)
        self.assertEqual(result.bottom_x, CALIBRATION_WIDTH - 1)
        self.assertEqual(result.bottom_y, CALIBRATION_HEIGHT - 1)

    def test_misplaced_rectangle_does_not_lock(self):
        calibrator = ProjectorCalibrator()
        frame = make_color_calibration_frame(rect_coords=(360, 20, 620, 220))

        for _ in range(5):
            calibrator.calibrate_projector(frame)

        result = calibrator.get_result()
        self.assertFalse(result.valid)
        self.assertFalse(result.locked)

    def test_otsu_grayscale_fallback_locks_low_contrast_markers(self):
        calibrator = ProjectorCalibrator()
        calibrator._threshold_var.set(150)
        frame = make_gray_calibration_frame(value=120)

        for _ in range(4):
            calibrator.calibrate_projector(frame)

        result = calibrator.get_result()
        self.assertTrue(result.valid)
        self.assertGreater(result.confidence, 0.5)


class FakeCapture:
    def __init__(self, frames, fps=30):
        self._frames = [frame.copy() for frame in frames]
        self._index = 0
        self._fps = fps
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        if self._index < len(self._frames):
            frame = self._frames[self._index]
            self._index += 1
            return True, frame.copy()
        return False, None

    def release(self):
        self.released = True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        return 0


class HookedCapture(FakeCapture):
    def __init__(self, frames, fps=30, hook=None):
        super().__init__(frames, fps)
        self._hook = hook

    def read(self):
        result = super().read()
        if self._hook is not None:
            self._hook(self._index, result[0])
        return result


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.query_params = {
            "arena_w": "800",
            "arena_h": "600",
        }

    async def send_json(self, payload):
        self.messages.append(payload)


class ConstantCalibrator:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def calibrate_projector(self, frame):
        self.calls += 1
        return frame

    def get_result(self):
        return self._result


class RecreatingDetector:
    def __init__(self, should_emit_shot=False):
        self.should_emit_shot = should_emit_shot
        self.roi_masks = []
        self.calls = 0

    def set_roi(self, mask):
        self.roi_masks.append(mask)

    def process_frame(self, frame, fps=30):
        self.calls += 1
        if self.should_emit_shot and self.roi_masks:
            return [
                {
                    "x": 141.25,
                    "y": 110.625,
                    "color": "red",
                    "confidence": 0.94,
                }
            ]
        return []


class ConfidenceDetector:
    def __init__(self):
        self.calls = 0
        self.roi_masks = []

    def set_roi(self, mask):
        self.roi_masks.append(mask)

    def process_frame(self, frame, fps=30):
        self.calls += 1
        if self.calls < 9:
            return []

        return [
            {
                "x": 141.25,
                "y": 94.5,
                "color": "red",
                "confidence": 0.18,
            },
            {
                "x": 141.25,
                "y": 110.625,
                "color": "red",
                "confidence": 0.94,
            },
        ]


class APISessionTests(unittest.IsolatedAsyncioTestCase):
    async def _run_session(
        self,
        frames,
        calibrator,
        ignore_color="none",
        timeout=None,
        detector_factory=None,
        debug_preview=False,
        active_bbox=None,
        calibration_confidence=None,
        force_calibration=False,
    ):
        prefs = {
            config_keys.VIDCAM: 0,
            config_keys.DETECTION_RATE: 1,
            config_keys.IGNORE_LASER_COLOR: ignore_color,
        }
        service = api_module.ShootOffAPI(
            prefs=prefs,
            calibrator=calibrator,
            detector_factory=detector_factory,
        )
        if active_bbox is not None:
            service.active_bbox = active_bbox
        if calibration_confidence is not None:
            service.calibration_confidence = calibration_confidence
        websocket = FakeWebSocket()
        capture = FakeCapture(frames)

        async def fast_sleep(*_args, **_kwargs):
            return None

        patches = [
            patch.object(api_module, "open_capture", return_value=capture),
            patch.object(api_module.asyncio, "sleep", new=fast_sleep),
        ]
        if timeout is not None:
            patches.append(patch.object(api_module, "CALIBRATION_TIMEOUT_SECONDS", timeout))

        with patches[0], patches[1]:
            if timeout is not None:
                with patches[2]:
                    await service.run_session(
                        websocket,
                        debug_preview=debug_preview,
                        force_calibration=force_calibration,
                    )
            else:
                await service.run_session(
                    websocket,
                    debug_preview=debug_preview,
                    force_calibration=force_calibration,
                )

        return websocket.messages

    async def test_manual_bbox_adjustment_accepts_dragged_bbox(self):
        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1) for _ in range(6)]
        calibrator = ConstantCalibrator(
            CalibrationResult(
                top_x=40,
                top_y=30,
                bottom_x=200,
                bottom_y=180,
                confidence=0.91,
                locked=True,
            )
        )
        service = api_module.ShootOffAPI(
            prefs={
                config_keys.VIDCAM: 0,
                config_keys.DETECTION_RATE: 1,
                config_keys.IGNORE_LASER_COLOR: "none",
            },
            calibrator=calibrator,
        )
        service.active_bbox = (40, 30, 200, 180)
        service.calibration_confidence = 0.91
        websocket = FakeWebSocket()
        capture = FakeCapture(frames)
        mouse_callback = None
        drag_sent = False

        async def fast_sleep(*_args, **_kwargs):
            return None

        def named_window(*_args, **_kwargs):
            return None

        def resize_window(*_args, **_kwargs):
            return None

        def imshow(*_args, **_kwargs):
            return None

        def destroy_window(*_args, **_kwargs):
            return None

        def set_mouse_callback(_window_name, callback):
            nonlocal mouse_callback
            mouse_callback = callback

        def wait_key(_delay):
            nonlocal drag_sent
            if mouse_callback is not None and not drag_sent:
                mouse_callback(api_module.cv2.EVENT_LBUTTONDOWN, 40, 30, 0, None)
                mouse_callback(
                    api_module.cv2.EVENT_MOUSEMOVE,
                    20,
                    20,
                    api_module.cv2.EVENT_FLAG_LBUTTON,
                    None,
                )
                mouse_callback(api_module.cv2.EVENT_LBUTTONUP, 20, 20, 0, None)
                drag_sent = True
                return 13
            return 0

        with patch.object(api_module, "open_capture", return_value=capture), \
                patch.object(api_module.asyncio, "sleep", new=fast_sleep), \
                patch.object(api_module.cv2, "namedWindow", side_effect=named_window), \
                patch.object(api_module.cv2, "resizeWindow", side_effect=resize_window), \
                patch.object(api_module.cv2, "imshow", side_effect=imshow), \
                patch.object(api_module.cv2, "destroyWindow", side_effect=destroy_window), \
                patch.object(api_module.cv2, "setMouseCallback", side_effect=set_mouse_callback), \
                patch.object(api_module.cv2, "waitKey", side_effect=wait_key):
            await service.run_session(websocket, debug_preview=True, force_calibration=True)

        statuses = [message.get("status") for message in websocket.messages if "status" in message]
        self.assertIn("manual_adjusting", statuses)
        self.assertIn("calibrated", statuses)
        manual_index = statuses.index("manual_adjusting")
        calibrated_index = statuses.index("calibrated", manual_index)
        self.assertLess(manual_index, calibrated_index)
        self.assertEqual(calibrator.calls, 0)
        self.assertEqual(service.active_bbox, (20, 20, 200, 180))
        self.assertEqual(service.calibration_confidence, 1.0)

    async def test_shot_payload_includes_confidence(self):
        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1) for _ in range(8)]
        laser = make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1)
        draw_laser_square(laser)
        frames.append(laser)

        calibrator = ConstantCalibrator(
            CalibrationResult(
                top_x=0,
                top_y=0,
                bottom_x=FRAME_WIDTH - 1,
                bottom_y=FRAME_HEIGHT - 1,
                confidence=0.9,
                locked=True,
            )
        )

        messages = await self._run_session(
            frames,
            calibrator,
            ignore_color="none",
            active_bbox=(0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1),
            calibration_confidence=0.9,
        )

        shot_messages = [message for message in messages if message.get("event") == "shot"]
        self.assertEqual(len(shot_messages), 1)
        shot = shot_messages[0]
        self.assertIn("confidence", shot)
        self.assertGreater(shot["confidence"], 0.0)
        self.assertEqual(shot["color"], "red")

    async def test_api_preserves_float_coordinates_and_prefers_best_candidate(self):
        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1) for _ in range(9)]
        calibrator = ConstantCalibrator(
            CalibrationResult(
                top_x=0,
                top_y=0,
                bottom_x=FRAME_WIDTH - 1,
                bottom_y=FRAME_HEIGHT - 1,
                confidence=0.9,
                locked=True,
            )
        )
        detector = ConfidenceDetector()

        messages = await self._run_session(
            frames,
            calibrator,
            ignore_color="none",
            detector_factory=lambda _w, _h: detector,
            active_bbox=(0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1),
            calibration_confidence=0.9,
        )

        shot_messages = [message for message in messages if message.get("event") == "shot"]
        self.assertEqual(len(shot_messages), 1)

        shot = shot_messages[0]
        self.assertAlmostEqual(shot["raw_x"], 141.25, places=2)
        self.assertAlmostEqual(shot["raw_y"], 110.625, places=3)
        self.assertEqual(shot["confidence"], 0.94)
        self.assertAlmostEqual(shot["x"], 141.25 * (800 / (FRAME_WIDTH - 1)), places=3)
        self.assertAlmostEqual(shot["y"], 110.625 * (600 / (FRAME_HEIGHT - 1)), places=3)
        self.assertTrue(detector.roi_masks)

    async def test_detector_roi_is_reapplied_after_recreation(self):
        prefs = {
            config_keys.VIDCAM: 0,
            config_keys.DETECTION_RATE: 1,
            config_keys.IGNORE_LASER_COLOR: "none",
            config_keys.LASER_INTENSITY: 230,
        }

        detectors = []

        def detector_factory(_width, _height):
            detector = RecreatingDetector(should_emit_shot=len(detectors) == 1)
            detectors.append(detector)
            return detector

        service = api_module.ShootOffAPI(
            prefs=prefs,
            calibrator=ConstantCalibrator(CalibrationResult()),
            detector_factory=detector_factory,
        )
        service.active_bbox = (0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1)
        service.calibration_confidence = 0.9

        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1) for _ in range(3)]
        frames[-1] = draw_laser_square(make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1))

        def bump_detector_intensity(read_count, _success):
            if read_count == 2:
                prefs[config_keys.LASER_INTENSITY] = 231

        capture = HookedCapture(frames, hook=bump_detector_intensity)
        websocket = FakeWebSocket()

        async def fast_sleep(*_args, **_kwargs):
            return None

        with patch.object(api_module, "open_capture", return_value=capture), \
                patch.object(api_module.asyncio, "sleep", new=fast_sleep):
            await service.run_session(websocket, debug_preview=False)

        shot_messages = [message for message in websocket.messages if message.get("event") == "shot"]
        self.assertEqual(len(shot_messages), 1)
        self.assertEqual(len(detectors), 2)
        self.assertTrue(detectors[0].roi_masks)
        self.assertTrue(detectors[1].roi_masks)

    async def test_ignore_laser_color_filters_red_shots(self):
        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1) for _ in range(8)]
        laser = make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1)
        draw_laser_square(laser)
        frames.append(laser)

        calibrator = ConstantCalibrator(
            CalibrationResult(
                top_x=0,
                top_y=0,
                bottom_x=FRAME_WIDTH - 1,
                bottom_y=FRAME_HEIGHT - 1,
                confidence=0.9,
                locked=True,
            )
        )

        messages = await self._run_session(
            frames,
            calibrator,
            ignore_color="red",
            active_bbox=(0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1),
            calibration_confidence=0.9,
        )
        shot_messages = [message for message in messages if message.get("event") == "shot"]
        self.assertEqual(len(shot_messages), 0)

    async def test_calibrated_bbox_is_reused_by_next_socket_session(self):
        prefs = {
            config_keys.VIDCAM: 0,
            config_keys.DETECTION_RATE: 1,
            config_keys.IGNORE_LASER_COLOR: "none",
        }
        calibrated = CalibrationResult(
            top_x=0,
            top_y=0,
            bottom_x=FRAME_WIDTH - 1,
            bottom_y=FRAME_HEIGHT - 1,
            confidence=0.9,
            locked=True,
        )
        service = api_module.ShootOffAPI(
            prefs=prefs,
            calibrator=ConstantCalibrator(calibrated),
        )
        service.active_bbox = (0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1)
        service.calibration_confidence = 0.9

        async def fast_sleep(*_args, **_kwargs):
            return None

        first_capture = FakeCapture([make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1)])
        first_socket = FakeWebSocket()
        with patch.object(api_module, "open_capture", return_value=first_capture), \
                patch.object(api_module.asyncio, "sleep", new=fast_sleep):
            await service.run_session(first_socket, debug_preview=False)

        self.assertEqual(service.active_bbox, (0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1))

        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1) for _ in range(8)]
        laser = make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1)
        draw_laser_square(laser)
        frames.append(laser)
        second_capture = FakeCapture(frames)
        second_socket = FakeWebSocket()
        service.calibrator = ConstantCalibrator(CalibrationResult())

        with patch.object(api_module, "open_capture", return_value=second_capture), \
                patch.object(api_module.asyncio, "sleep", new=fast_sleep):
            await service.run_session(second_socket, debug_preview=False)

        shot_messages = [message for message in second_socket.messages if message.get("event") == "shot"]
        self.assertEqual(len(shot_messages), 1)

    async def test_cached_calibration_is_announced_to_shot_stream(self):
        frames = [make_frame(FRAME_WIDTH, FRAME_HEIGHT, background=1)]
        service = api_module.ShootOffAPI(
            prefs={
                config_keys.VIDCAM: 0,
                config_keys.DETECTION_RATE: 1,
                config_keys.IGNORE_LASER_COLOR: "none",
            },
            calibrator=ConstantCalibrator(CalibrationResult()),
        )
        service.active_bbox = (0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1)
        service.calibration_confidence = 0.88
        websocket = FakeWebSocket()
        capture = FakeCapture(frames)

        async def fast_sleep(*_args, **_kwargs):
            return None

        with patch.object(api_module, "open_capture", return_value=capture), \
                patch.object(api_module.asyncio, "sleep", new=fast_sleep):
            await service.run_session(websocket, debug_preview=False)

        self.assertEqual(websocket.messages[0]["status"], "calibrated")
        self.assertEqual(websocket.messages[0]["mode"], "cached")
        self.assertEqual(websocket.messages[0]["bbox"], [0, 0, FRAME_WIDTH - 1, FRAME_HEIGHT - 1])

if __name__ == "__main__":
    unittest.main(verbosity=2)
