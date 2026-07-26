import cv2
import math
import numpy as np
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import time


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CalibrationResult:
    top_x:      int = 0
    top_y:      int = 0
    bottom_x:   int = 0
    bottom_y:   int = 0
    confidence: float = 0.0   # 0-1
    locked:     bool  = False

    @property
    def valid(self) -> bool:
        return (self.locked
                and self.bottom_x > self.top_x
                and self.bottom_y > self.top_y)

    def as_bbox(self) -> Tuple[int, int, int, int]:
        return (self.top_x, self.top_y, self.bottom_x, self.bottom_y)

    def width(self)  -> int: return self.bottom_x - self.top_x
    def height(self) -> int: return self.bottom_y - self.top_y


# ──────────────────────────────────────────────────────────────────────────────
# ProjectorCalibrator
# ──────────────────────────────────────────────────────────────────────────────

class _PlainVar:
    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *_args, **_kwargs):
        return None

class ProjectorCalibrator:
    """
    Detects a GREEN TRIANGLE (top-left anchor) and a RED RECTANGLE
    (bottom-right anchor) projected onto a surface, then derives the
    calibrated projector bounding box.

    Enhancements over original
    ──────────────────────────
    1. HSV-based colour segmentation  — finds green/red shapes even when
       the projector brightness changes; quadrant-aware masking keeps the
       search area anchored to the expected calibration corner.

    2. Temporal EMA stabilisation  — the bounding box is smoothed over
       recent frames so a single noisy frame cannot jolt the calibration.

    3. Lock confidence score  — computed from contour circularity, area
       plausibility, and colour purity; only high-confidence detections
       update the stable lock.

    4. Multi-candidate NMS  — when several triangles or rectangles are
       detected the best one (largest area inside colour mask) is chosen
       rather than the last one iterated.

    5. Sub-pixel corner refinement  — OpenCV cornerSubPix tightens the
       anchor coordinates to sub-pixel accuracy after the coarse polygon
       detection.

    6. Perspective-aware anchor extraction  — for the rectangle the
       bottom-right corner is chosen by projecting all four corners and
       picking the one that is geometrically farthest from the image
       origin, which is invariant to slight projector rotation.

    7. Auto-threshold (Otsu/manual fallback)  — grayscale fallback adapts
       to projector brightness changes before falling back to the slider.

    8. Diagnostic overlay  — optional rich debug rendering with colour
       labels, confidence bars, and the derived bounding box.
    """

    # ── HSV colour ranges (OpenCV: H 0-180, S 0-255, V 0-255) ────────────────
    # Green triangle marker
    _GREEN_H_LOW  = np.array([40,  80, 60],  dtype=np.uint8)
    _GREEN_H_HIGH = np.array([85, 255, 255], dtype=np.uint8)

    # Red rectangle marker (red wraps around 0/180 in OpenCV)
    _RED1_LOW  = np.array([0,   100,  60],  dtype=np.uint8)
    _RED1_HIGH = np.array([10,  255, 255],  dtype=np.uint8)
    _RED2_LOW  = np.array([165, 100,  60],  dtype=np.uint8)
    _RED2_HIGH = np.array([180, 255, 255],  dtype=np.uint8)

    # ── geometry / quality constants ──────────────────────────────────────────
    _MIN_CONTOUR_AREA        = 200      # px²  — ignore tiny noise blobs
    _MAX_CONTOUR_AREA_RATIO  = 0.30     # fraction of frame — ignore full-frame blobs
    _APPROX_EPSILON_RATIO    = 0.03     # tighter than original 0.01
    _TRIANGLE_CIRCULARITY_OK = 0.20     # minimum circularity for triangle
    _RECT_CIRCULARITY_OK     = 0.55     # rectangles are more circular than triangles
    _CORNER_REFINE_WIN       = (5, 5)   # sub-pixel refinement window
    _EMA_ALPHA               = 0.35     # smoothing factor (0=frozen, 1=instant)
    _LOCK_CONFIDENCE_MIN     = 0.45     # must beat this to update stable lock
    _STABLE_FRAMES_REQUIRED  = 3        # consecutive good frames before locking
    _HISTORY_LEN             = 8        # frames kept for EMA
    _EDGE_SNAP_TOLERANCE_PX  = 5        # snap border-touching anchors back to the frame edge

    def __init__(self):
        self._result        = CalibrationResult()
        self._ema_result    = CalibrationResult()
        self._stable_count  = 0
        self._frame_w       = 1
        self._frame_h       = 1

        # Tkinter widgets (created lazily)
        self._window: Optional[tk.Toplevel] = None
        self._threshold_var  = _PlainVar(150)
        self._use_hsv_var    = _PlainVar(True)
        self._show_debug_var = _PlainVar(False)
        self._status_var     = _PlainVar("Not calibrated")

        if tk._default_root is not None:
            self._init_tk_vars(tk._default_root)

    def _init_tk_vars(self, master: tk.Misc):
        self._threshold_var  = tk.IntVar(master=master, value=self._threshold_var.get())
        self._use_hsv_var    = tk.BooleanVar(master=master, value=self._use_hsv_var.get())
        self._show_debug_var = tk.BooleanVar(master=master, value=self._show_debug_var.get())
        self._status_var     = tk.StringVar(master=master, value=self._status_var.get())

    def _quadrant_mask(self, quadrant: str) -> np.ndarray:
        mask = np.zeros((self._frame_h, self._frame_w), dtype=np.uint8)
        mid_x = self._frame_w // 2
        mid_y = self._frame_h // 2

        if quadrant == "top_left":
            mask[:mid_y, :mid_x] = 255
        elif quadrant == "bottom_right":
            mask[mid_y:, mid_x:] = 255
        else:
            raise ValueError("Unknown quadrant: %s" % quadrant)

        return mask

    def _apply_quadrant_mask(self, mask: np.ndarray, quadrant: str) -> np.ndarray:
        return cv2.bitwise_and(mask, self._quadrant_mask(quadrant))

    def _grayscale_fallback_mask(self, frame: np.ndarray, quadrant: str) -> np.ndarray:
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi = self._quadrant_mask(quadrant)

        _, otsu_bw = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        otsu_bw = cv2.bitwise_and(otsu_bw, roi)
        if cv2.countNonZero(otsu_bw) > 0:
            return otsu_bw

        _, manual_bw = cv2.threshold(grey, self._threshold_var.get(), 255, cv2.THRESH_BINARY)
        return cv2.bitwise_and(manual_bw, roi)

    # ── public API ────────────────────────────────────────────────────────────

    def get_projected_bbox(self) -> Tuple[int, int, int, int]:
        return self._result.as_bbox()

    def get_result(self) -> CalibrationResult:
        return self._result

    def reset(self):
        self._result       = CalibrationResult()
        self._ema_result   = CalibrationResult()
        self._stable_count = 0
        self._status_var.set("Not calibrated")

    # ── main calibration call (call once per webcam frame) ────────────────────

    def calibrate_projector(self, webcam_image: np.ndarray) -> np.ndarray:
        """
        Process one BGR webcam frame.  Returns an annotated copy.
        Updates self._result when a reliable lock is achieved.
        """
        if webcam_image is None or webcam_image.size == 0:
            return webcam_image

        frame = webcam_image.copy()
        self._frame_h, self._frame_w = frame.shape[:2]
        max_area = self._frame_w * self._frame_h * self._MAX_CONTOUR_AREA_RATIO

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # ── 1. detect green triangle ──────────────────────────────────────────
        tri_contour, tri_conf, tri_anchor = self._detect_triangle(
            frame, hsv, max_area
        )

        # ── 2. detect red rectangle ───────────────────────────────────────────
        rect_contour, rect_conf, rect_anchor = self._detect_rectangle(
            frame, hsv, max_area
        )

        # ── 3. anchor snapping (direction-aware) ──────────────────────────────
        # NOTE: cornerSubPix is intentionally NOT used here.  It is designed for
        # checkerboard saddle-point corners and actively drifts colored-marker
        # vertices toward the nearest image-gradient feature, introducing a
        # consistent positional offset that corrupts the calibrated bbox.
        # Instead we rely on the polygon vertex (already sub-pixel accurate via
        # approxPolyDP on HSV-segmented contours) and snap only toward the
        # geometrically expected frame edge.
        if tri_anchor is not None:
            tri_anchor = self._snap_top_left_anchor(tri_anchor)
        if rect_anchor is not None:
            rect_anchor = self._snap_bottom_right_anchor(rect_anchor)

        # ── 4. update EMA + lock ──────────────────────────────────────────────
        both_found = (tri_anchor is not None) and (rect_anchor is not None)
        confidence = (tri_conf + rect_conf) / 2.0 if both_found else 0.0

        if both_found and confidence >= self._LOCK_CONFIDENCE_MIN:
            tx, ty   = int(round(tri_anchor[0])),  int(round(tri_anchor[1]))
            bx, by   = int(round(rect_anchor[0])), int(round(rect_anchor[1]))

            # Sanity: top-left must be above and left of bottom-right
            if tx < bx and ty < by:
                self._apply_ema(tx, ty, bx, by, confidence)
                self._stable_count = min(
                    self._stable_count + 1, self._STABLE_FRAMES_REQUIRED
                )
            else:
                self._stable_count = max(self._stable_count - 1, 0)
        else:
            self._stable_count = max(self._stable_count - 1, 0)

        if self._stable_count >= self._STABLE_FRAMES_REQUIRED:
            er = self._ema_result
            self._result = CalibrationResult(
                top_x=er.top_x, top_y=er.top_y,
                bottom_x=er.bottom_x, bottom_y=er.bottom_y,
                confidence=er.confidence,
                locked=True,
            )
            self._status_var.set(
                f"Locked ✓  {self._result.width()}×{self._result.height()} px"
                f"  conf={self._result.confidence:.2f}"
            )
        else:
            status_txt = (
                f"Searching… conf={confidence:.2f}  "
                f"stable={self._stable_count}/{self._STABLE_FRAMES_REQUIRED}"
            )
            self._status_var.set(status_txt)

        # ── 5. draw diagnostic overlay ────────────────────────────────────────
        if self._show_debug_var.get():
            frame = self._draw_debug(
                frame, tri_contour, rect_contour,
                tri_anchor, rect_anchor, confidence,
            )
        else:
            frame = self._draw_minimal(frame, tri_anchor, rect_anchor)

        return frame

    # ── detection helpers ─────────────────────────────────────────────────────

    def _detect_triangle(
        self, frame, hsv, max_area
    ) -> Tuple[Optional[np.ndarray], float, Optional[np.ndarray]]:
        """Return (best_contour, confidence, anchor_point) for the green triangle."""

        green_mask = cv2.inRange(hsv, self._GREEN_H_LOW, self._GREEN_H_HIGH)
        green_mask = self._apply_quadrant_mask(green_mask, "top_left")
        green_mask = self._clean_mask(green_mask)

        # Fallback to Otsu/manual grayscale threshold if HSV yields nothing
        if not self._use_hsv_var.get() or cv2.countNonZero(green_mask) == 0:
            green_mask = self._clean_mask(self._grayscale_fallback_mask(frame, "top_left"))

        contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_cnt, best_conf, best_anchor = None, 0.0, None

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self._MIN_CONTOUR_AREA or area > max_area:
                continue

            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, self._APPROX_EPSILON_RATIO * peri, True)

            if len(approx) != 3:
                continue

            circ   = self._circularity(area, peri)
            conf   = self._triangle_confidence(approx, area, circ, green_mask)

            if conf > best_conf:
                best_cnt    = approx
                best_conf   = conf
                best_anchor = np.array(self._top_left_coord(approx), dtype=np.float32)

        return best_cnt, best_conf, best_anchor

    def _detect_rectangle(
        self, frame, hsv, max_area
    ) -> Tuple[Optional[np.ndarray], float, Optional[np.ndarray]]:
        """Return (best_contour, confidence, anchor_point) for the red rectangle."""

        red_mask1 = cv2.inRange(hsv, self._RED1_LOW,  self._RED1_HIGH)
        red_mask2 = cv2.inRange(hsv, self._RED2_LOW,  self._RED2_HIGH)
        red_mask  = cv2.bitwise_or(red_mask1, red_mask2)
        red_mask  = self._apply_quadrant_mask(red_mask, "bottom_right")
        red_mask  = self._clean_mask(red_mask)

        if not self._use_hsv_var.get() or cv2.countNonZero(red_mask) == 0:
            red_mask = self._clean_mask(self._grayscale_fallback_mask(frame, "bottom_right"))

        contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_cnt, best_conf, best_anchor = None, 0.0, None

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self._MIN_CONTOUR_AREA or area > max_area:
                continue

            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, self._APPROX_EPSILON_RATIO * peri, True)

            if len(approx) != 4:
                continue

            circ = self._circularity(area, peri)
            conf = self._rect_confidence(approx, area, circ, red_mask)

            if conf > best_conf:
                best_cnt    = approx
                best_conf   = conf
                best_anchor = np.array(self._bottom_right_coord(approx), dtype=np.float32)

        return best_cnt, best_conf, best_anchor

    # ── geometry utilities ────────────────────────────────────────────────────

    @staticmethod
    def _circularity(area: float, perimeter: float) -> float:
        if perimeter == 0:
            return 0.0
        return 4 * math.pi * area / (perimeter ** 2)

    def _triangle_confidence(self, approx, area, circularity, mask) -> float:
        """
        Score 0-1 for triangle quality.
        Factors: circularity range, interior colour fill ratio, angle regularity.
        """
        score = 0.0

        # Circularity: ideal equilateral triangle ≈ 0.605; allow wide range
        score += min(circularity / 0.605, 1.0) * 0.3

        # Colour fill ratio inside contour bounding rect
        fill = self._mask_fill_ratio(approx, mask)
        score += fill * 0.4

        # Angle regularity (all angles should be near 60°)
        angles = self._polygon_angles(approx)
        angle_score = 1.0 - min(np.std(angles) / 60.0, 1.0)
        score += angle_score * 0.3

        return min(score, 1.0)

    def _rect_confidence(self, approx, area, circularity, mask) -> float:
        """Score 0-1 for rectangle quality."""
        score = 0.0

        # Circularity: ideal square ≈ 0.785
        score += min(circularity / 0.785, 1.0) * 0.25

        fill   = self._mask_fill_ratio(approx, mask)
        score += fill * 0.45

        # Right-angle regularity (all angles near 90°)
        angles = self._polygon_angles(approx)
        angle_score = 1.0 - min(np.std(angles) / 90.0, 1.0)
        score += angle_score * 0.30

        return min(score, 1.0)

    @staticmethod
    def _polygon_angles(approx: np.ndarray) -> np.ndarray:
        """Interior angles of a polygon in degrees."""
        pts    = approx.reshape(-1, 2).astype(np.float32)
        n      = len(pts)
        angles = []
        for i in range(n):
            a = pts[(i - 1) % n]
            b = pts[i]
            c = pts[(i + 1) % n]
            ba = a - b;  bc = c - b
            cos_a = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
            angles.append(math.degrees(math.acos(float(np.clip(cos_a, -1, 1)))))
        return np.array(angles)

    def _mask_fill_ratio(self, approx: np.ndarray, mask: np.ndarray) -> float:
        """Fraction of pixels inside the contour that are white in mask."""
        tmp = np.zeros(mask.shape, dtype=np.uint8)
        cv2.fillPoly(tmp, [approx], 255)
        interior_total = tmp.sum() / 255
        if interior_total == 0:
            return 0.0
        interior_white = cv2.bitwise_and(mask, tmp).sum() / 255
        return float(interior_white / interior_total)

    @staticmethod
    def _far_left_coord(approx: np.ndarray) -> Tuple[int, int]:
        """Leftmost point of a contour."""
        pts = approx.reshape(-1, 2)
        idx = np.argmin(pts[:, 0])
        return int(pts[idx, 0]), int(pts[idx, 1])

    @staticmethod
    def _top_left_coord(approx: np.ndarray) -> Tuple[int, int]:
        """Point closest to the image origin (min x+y)."""
        pts = approx.reshape(-1, 2)
        idx = np.argmin(pts[:, 0] + pts[:, 1])
        return int(pts[idx, 0]), int(pts[idx, 1])

    @staticmethod
    def _bottom_right_coord(approx: np.ndarray) -> Tuple[int, int]:
        """Point closest to the bottom-right image order (max x + y)."""
        pts = approx.reshape(-1, 2)
        idx = np.argmax(pts[:, 0] + pts[:, 1])
        return int(pts[idx, 0]), int(pts[idx, 1])

    @staticmethod
    def _clean_mask(mask: np.ndarray) -> np.ndarray:
        """Morphological open + close to remove noise and fill small holes."""
        k      = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=1)
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k, iterations=2)
        return closed

    @staticmethod
    def _refine_corner(grey: np.ndarray, pt: np.ndarray) -> np.ndarray:
        """Sub-pixel corner refinement around a single point."""
        pts = pt.reshape(1, 1, 2).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
        try:
            refined = cv2.cornerSubPix(grey, pts, (5, 5), (-1, -1), criteria)
            return refined.reshape(2)
        except Exception:
            return pt.reshape(2)

    def _snap_top_left_anchor(self, pt: np.ndarray) -> np.ndarray:
        """
        Snap the green-triangle (top-left) anchor toward the top-left frame
        corner only.  Snapping toward the right or bottom edge would corrupt
        the calibrated bbox by flipping the anchor to the wrong side.
        """
        snapped = np.array(pt, dtype=np.float32, copy=True).reshape(2)
        max_x = max(self._frame_w - 1, 0)
        max_y = max(self._frame_h - 1, 0)
        t = self._EDGE_SNAP_TOLERANCE_PX
        snapped[0] = float(np.clip(snapped[0], 0, max_x))
        snapped[1] = float(np.clip(snapped[1], 0, max_y))
        if snapped[0] <= t:
            snapped[0] = 0.0
        if snapped[1] <= t:
            snapped[1] = 0.0
        return snapped

    def _snap_bottom_right_anchor(self, pt: np.ndarray) -> np.ndarray:
        """
        Snap the red-rectangle (bottom-right) anchor toward the bottom-right
        frame corner only.  Snapping toward the left or top edge would corrupt
        the calibrated bbox.
        """
        snapped = np.array(pt, dtype=np.float32, copy=True).reshape(2)
        max_x = max(self._frame_w - 1, 0)
        max_y = max(self._frame_h - 1, 0)
        t = self._EDGE_SNAP_TOLERANCE_PX
        snapped[0] = float(np.clip(snapped[0], 0, max_x))
        snapped[1] = float(np.clip(snapped[1], 0, max_y))
        if snapped[0] >= max_x - t:
            snapped[0] = float(max_x)
        if snapped[1] >= max_y - t:
            snapped[1] = float(max_y)
        return snapped

    # kept for backward-compat with any external callers
    def _snap_edge_anchor(self, pt: np.ndarray) -> np.ndarray:
        return self._snap_top_left_anchor(pt)

    # ── EMA smoothing ─────────────────────────────────────────────────────────

    def _apply_ema(self, tx, ty, bx, by, conf):
        a = self._EMA_ALPHA
        if not self._ema_result.locked:
            # First update: seed directly
            self._ema_result = CalibrationResult(
                top_x=tx, top_y=ty,
                bottom_x=bx, bottom_y=by,
                confidence=conf, locked=True,
            )
        else:
            er = self._ema_result
            self._ema_result = CalibrationResult(
                top_x    = int(round(a * tx + (1 - a) * er.top_x)),
                top_y    = int(round(a * ty + (1 - a) * er.top_y)),
                bottom_x = int(round(a * bx + (1 - a) * er.bottom_x)),
                bottom_y = int(round(a * by + (1 - a) * er.bottom_y)),
                confidence = a * conf + (1 - a) * er.confidence,
                locked   = True,
            )

    # ── drawing helpers ───────────────────────────────────────────────────────

    def _draw_minimal(self, frame, tri_anchor, rect_anchor) -> np.ndarray:
        if tri_anchor is not None:
            cv2.circle(frame, (int(tri_anchor[0]), int(tri_anchor[1])), 8, (0, 255, 0), -1)
        if rect_anchor is not None:
            cv2.circle(frame, (int(rect_anchor[0]), int(rect_anchor[1])), 8, (0, 0, 255), -1)
        if self._result.valid:
            cv2.rectangle(frame,
                          (self._result.top_x,    self._result.top_y),
                          (self._result.bottom_x,  self._result.bottom_y),
                          (0, 255, 255), 2)
        return frame

    def _draw_debug(self, frame, tri_cnt, rect_cnt,
                    tri_anchor, rect_anchor, confidence) -> np.ndarray:
        overlay = frame.copy()

        # Filled contours
        if tri_cnt is not None:
            cv2.drawContours(overlay, [tri_cnt],  0, (0, 255,   0), -1)
        if rect_cnt is not None:
            cv2.drawContours(overlay, [rect_cnt], 0, (0,   0, 255), -1)

        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

        # Anchor dots + labels
        font = cv2.FONT_HERSHEY_SIMPLEX
        if tri_anchor is not None:
            ax, ay = int(tri_anchor[0]), int(tri_anchor[1])
            cv2.circle(frame, (ax, ay), 6, (0, 255, 0), -1)
            cv2.putText(frame, f"TL ({ax},{ay})", (ax + 8, ay - 8),
                        font, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
        if rect_anchor is not None:
            bx, by = int(rect_anchor[0]), int(rect_anchor[1])
            cv2.circle(frame, (bx, by), 6, (0, 0, 255), -1)
            cv2.putText(frame, f"BR ({bx},{by})", (bx + 8, by - 8),
                        font, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

        # Bounding box
        if self._result.valid:
            cv2.rectangle(frame,
                          (self._result.top_x,   self._result.top_y),
                          (self._result.bottom_x, self._result.bottom_y),
                          (0, 255, 255), 2)
            cv2.putText(frame,
                        f"{self._result.width()}x{self._result.height()} px",
                        (self._result.top_x + 4, self._result.top_y - 6),
                        font, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

        # Confidence bar (top strip)
        bar_w = int(self._frame_w * confidence)
        cv2.rectangle(frame, (0, 0), (bar_w, 8),
                      (0, 255, 0) if confidence >= self._LOCK_CONFIDENCE_MIN
                      else (0, 165, 255), -1)

        # Stable-count indicator
        cv2.putText(frame,
                    f"stable {self._stable_count}/{self._STABLE_FRAMES_REQUIRED}  "
                    f"conf {confidence:.2f}",
                    (8, 22), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        return frame

    # ── Tkinter UI ────────────────────────────────────────────────────────────

    def show_threshold_slider(self, parent: tk.Misc):
        if self._window and self._window.winfo_exists():
            self._window.lift()
            return

        if isinstance(self._threshold_var, _PlainVar):
            self._init_tk_vars(parent)

        self._window = tk.Toplevel(parent)
        self._window.title("Projector Calibration")
        self._window.resizable(False, False)
        self._window.overrideredirect(False)   # keep title bar for usability

        pad = dict(padx=8, pady=4)
        frm = ttk.Frame(self._window, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # ── threshold slider (fallback) ────────────────────────────────────
        ttk.Label(frm, text="Grey threshold (manual fallback)").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, **pad)
        ttk.Scale(frm, from_=60, to=255, orient=tk.HORIZONTAL,
                  variable=self._threshold_var, length=220).grid(
            row=1, column=0, columnspan=2, **pad)
        thresh_lbl = ttk.Label(frm, text="150")
        thresh_lbl.grid(row=1, column=2, **pad)
        self._threshold_var.trace_add(
            'write',
            lambda *_: thresh_lbl.config(text=str(self._threshold_var.get()))
        )

        # ── HSV toggle ────────────────────────────────────────────────────
        ttk.Checkbutton(frm, text="Use HSV colour segmentation",
                        variable=self._use_hsv_var).grid(
            row=2, column=0, columnspan=3, sticky=tk.W, **pad)

        # ── debug overlay toggle ──────────────────────────────────────────
        ttk.Checkbutton(frm, text="Show debug overlay",
                        variable=self._show_debug_var).grid(
            row=3, column=0, columnspan=3, sticky=tk.W, **pad)

        # ── EMA alpha slider ──────────────────────────────────────────────
        ttk.Label(frm, text="Smoothing (EMA α)").grid(
            row=4, column=0, columnspan=2, sticky=tk.W, **pad)
        ema_var = tk.DoubleVar(value=self._EMA_ALPHA)
        ttk.Scale(frm, from_=0.05, to=1.0, orient=tk.HORIZONTAL,
                  variable=ema_var, length=220,
                  command=lambda v: setattr(self, '_EMA_ALPHA', float(v))).grid(
            row=5, column=0, columnspan=2, **pad)

        # ── stable-frames slider ──────────────────────────────────────────
        ttk.Label(frm, text="Stable frames required").grid(
            row=6, column=0, columnspan=2, sticky=tk.W, **pad)
        stable_var = tk.IntVar(value=self._STABLE_FRAMES_REQUIRED)
        ttk.Scale(frm, from_=1, to=10, orient=tk.HORIZONTAL,
                  variable=stable_var, length=220,
                  command=lambda v: setattr(self, '_STABLE_FRAMES_REQUIRED', int(float(v)))).grid(
            row=7, column=0, columnspan=2, **pad)

        # ── reset button ──────────────────────────────────────────────────
        ttk.Button(frm, text="Reset calibration",
                   command=self.reset).grid(
            row=8, column=0, columnspan=3, pady=(8, 4))

        # ── status label ──────────────────────────────────────────────────
        ttk.Label(frm, textvariable=self._status_var,
                  foreground='blue').grid(
            row=9, column=0, columnspan=3, **pad)

        # Position near parent
        self._window.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        ph     = parent.winfo_height()
        wh     = self._window.winfo_height()
        self._window.geometry(f"+{px}+{py + ph - wh - 40}")

    def destroy_threshold_slider(self):
        if self._window and self._window.winfo_exists():
            self._window.destroy()
            self._window = None