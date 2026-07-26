"""
Standalone ShootOFF API — Zhang's-Method Projector Calibration.

Zhang's method replaces the legacy 2-anchor (triangle + rectangle) bbox
approach with a full perspective homography pipeline:

    1. Detect up to 4 coloured corner markers in each frame:
          TL → Green  Triangle     (top-left quadrant)
          TR → Blue   Circle       (top-right quadrant)   ← NEW
          BR → Red    Rectangle    (bottom-right quadrant)
          BL → Yellow Diamond      (bottom-left quadrant) ← NEW

    2. Accumulate marker observations across N frames
       (mirrors Zhang's "multiple views from different angles" concept).

    3. Once enough observations are collected, compute a robust 3×3
       perspective homography H via cv2.findHomography + RANSAC.
       H maps camera-pixel coordinates → normalised arena [0, 1]².

    4. H is refined each frame via Exponential Moving Average so the
       calibration adapts to slow mechanical drift without jitter.

    5. Optional camera intrinsics (K, dist_coeffs) – loaded from a
       JSON / YAML file – are applied with cv2.undistortPoints before
       homography estimation, giving the full Zhang pipeline.

    6. Shot coordinates are warped through H instead of the old linear
       bbox scaling, correcting lens distortion and perspective skew.

    Fallback: if only TL + BR markers are visible (legacy 2-marker
    rig) the system degrades gracefully to the affine bbox approach.

Third-party requirements:
    pip install fastapi uvicorn opencv-python numpy
"""

# ──────────────────────────────────────────────────────────────────────────────
# Standard-library / third-party imports
# ──────────────────────────────────────────────────────────────────────────────

import argparse
import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Configuration keys  (from configurator.py)
# ══════════════════════════════════════════════════════════════════════════════

DEBUG                           = "debug"
DETECTION_RATE                  = "detectionrate"
LASER_INTENSITY                 = "laserintensity"
IGNORE_LASER_COLOR              = "ignorelasercolor"
VIDCAM                          = "vidcam"
SHOT_LUMINANCE_MODE             = "shotluminancemode"
SHOT_EXCESSIVE_BRIGHTNESS_RATIO = "shotexcessivebrightnessratio"
SHOT_MIN_DIMENSION              = "shotmindimension"
SHOT_DYNAMIC_RATIO_CAP          = "shotdynamicratiocap"
SHOT_USE_DYNAMIC_THRESHOLD      = "shotusedynamicthreshold"
SHOT_USE_EXCESSIVE_MASK         = "shotuseexcessivemask"
SHOT_USE_VARIANCE_THRESHOLD     = "shotusevariancethreshold"
SHOT_VARIANCE_ALPHA             = "shotvariancealpha"
SHOT_VARIANCE_K                 = "shotvariancek"
SHOT_USE_TEMPORAL_FILTER        = "shotusetemporalfilter"
SHOT_TEMPORAL_WINDOW            = "shottemporalwindow"
SHOT_TEMPORAL_MIN_FRAMES        = "shottemporalminframes"

_DEFAULT_PREFERENCES: Dict = {
    DEBUG:                           False,
    DETECTION_RATE:                  50,
    LASER_INTENSITY:                 50,
    IGNORE_LASER_COLOR:              "none",
    VIDCAM:                          3,
    SHOT_LUMINANCE_MODE:             "combined",
    SHOT_EXCESSIVE_BRIGHTNESS_RATIO: 0.9,
    SHOT_MIN_DIMENSION:              8,
    SHOT_DYNAMIC_RATIO_CAP:          0.25,
    SHOT_USE_DYNAMIC_THRESHOLD:      True,
    SHOT_USE_EXCESSIVE_MASK:         True,
    SHOT_USE_VARIANCE_THRESHOLD:     True,
    SHOT_VARIANCE_ALPHA:             0.05,
    SHOT_VARIANCE_K:                 1.5,
    SHOT_USE_TEMPORAL_FILTER:        True,
    SHOT_TEMPORAL_WINDOW:            3,
    SHOT_TEMPORAL_MIN_FRAMES:        1,
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Configurator
# ══════════════════════════════════════════════════════════════════════════════

class Configurator:
    def _check_rate(self, rate):
        value = int(rate)
        if value < 1:
            raise argparse.ArgumentTypeError(
                "DETECTION_RATE must be a number greater than 0")
        return value

    def _check_intensity(self, intensity):
        value = int(intensity)
        if value < 1 or value > 255:
            raise argparse.ArgumentTypeError(
                "LASER_INTENSITY must be a number between 1 and 255")
        return value

    def _check_vidcam(self, vidcam):
        try:
            value = int(vidcam)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            return vidcam

    def _check_ignore_laser_color(self, ignore_laser_color):
        v = ignore_laser_color.lower()
        if v not in ("none", "red", "green"):
            raise argparse.ArgumentTypeError(
                'IGNORE_LASER_COLOR must be "none", "green", or "red"')
        return v

    def __init__(self, argv=None):
        preferences = dict(_DEFAULT_PREFERENCES)

        parser = argparse.ArgumentParser(prog="api.py")
        parser.add_argument("-d", "--debug", action="store_true")
        parser.add_argument("-r", "--detection-rate",  type=self._check_rate)
        parser.add_argument("-i", "--laser-intensity", type=self._check_intensity)
        parser.add_argument("-v", "--vidcam",          type=self._check_vidcam)
        parser.add_argument("-c", "--ignore-laser-color",
                            type=self._check_ignore_laser_color)

        args = parser.parse_args(argv)
        preferences[DEBUG] = args.debug
        if args.detection_rate:
            preferences[DETECTION_RATE]  = int(args.detection_rate)
        if args.laser_intensity:
            preferences[LASER_INTENSITY] = int(args.laser_intensity)
        if args.vidcam is not None:
            preferences[VIDCAM] = (
                int(args.vidcam) if str(args.vidcam).isdigit() else args.vidcam)
        if args.ignore_laser_color:
            preferences[IGNORE_LASER_COLOR] = args.ignore_laser_color

        self._preferences = preferences

    def get_preferences(self):
        return self._preferences


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Zhang's-Method Projector Calibrator
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CalibrationResult:
    """
    Extended calibration result carrying both the legacy bounding-box
    (for backward compatibility) and the Zhang homography.
    """
    top_x:      int   = 0
    top_y:      int   = 0
    bottom_x:   int   = 0
    bottom_y:   int   = 0
    confidence: float = 0.0
    locked:     bool  = False

    # ── Zhang's method additions ──────────────────────────────────────────────
    # 3×3 float32 matrix mapping camera pixels → normalised arena [0,1]²
    homography:   Optional[np.ndarray] = field(default=None, repr=False)
    # Camera-pixel positions of the four detected corners (TL,TR,BR,BL)
    corners_px:   Optional[np.ndarray] = field(default=None, repr=False)
    # How many of the 4 markers were actually detected (2 or 4)
    marker_count: int = 0
    # Reprojection error of the RANSAC homography fit (pixels)
    reproj_error: float = 0.0

    @property
    def valid(self) -> bool:
        return (self.locked
                and self.bottom_x > self.top_x
                and self.bottom_y > self.top_y)

    @property
    def has_homography(self) -> bool:
        return self.homography is not None and self.homography.shape == (3, 3)

    def as_bbox(self) -> Tuple[int, int, int, int]:
        return (self.top_x, self.top_y, self.bottom_x, self.bottom_y)

    def width(self)  -> int: return self.bottom_x - self.top_x
    def height(self) -> int: return self.bottom_y - self.top_y


class _PlainVar:
    def __init__(self, value=None):
        self._value = value
    def get(self):               return self._value
    def set(self, value):        self._value = value
    def trace_add(self, *_, **__): return None


# ── Zhang normalised destination corners (TL, TR, BR, BL in arena [0,1]²) ───
_ZHANG_DST = np.array(
    [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
    dtype=np.float32,
)


class ProjectorCalibrator:
    """
    Zhang's-Method projector-camera calibration.

    MARKER LAYOUT (shapes projected onto the shooting surface):
    ┌──────────────────────────────────┐
    │ ▲ Green Triangle   ● Blue Circle │
    │   (Top-Left)         (Top-Right) │
    │                                  │
    │ ◆ Yellow Diamond  ■ Red Rect.    │
    │   (Bottom-Left)   (Bottom-Right) │
    └──────────────────────────────────┘

    With 4 markers → full perspective homography (Zhang's method).
    With 2 markers (TL + BR only) → legacy affine bbox fallback.

    Multi-frame accumulation
    ─────────────────────────
    Zhang's original insight is that a single view is insufficient for
    a robust calibration; multiple observations are needed to solve the
    over-determined system.  Here each camera frame that yields detected
    markers is stored as one "observation".  After
    ZHANG_MIN_OBSERVATIONS frames, cv2.findHomography (RANSAC) is called
    on the accumulated point set, equivalent to fitting a plane-to-plane
    homography from many noisy correspondences.

    Camera intrinsics (optional)
    ─────────────────────────────
    If a camera_calibration.json (or .yml) file is present the intrinsic
    matrix K and distortion coefficients are loaded, and every detected
    marker position is undistorted with cv2.undistortPoints before the
    homography is computed – completing the full Zhang pipeline.

    EMA homography refinement
    ─────────────────────────
    After the initial lock, every new observation updates the homography
    via element-wise Exponential Moving Average so the calibration adapts
    to slow projector/camera drift without introducing jitter.
    """

    # ── Marker HSV colour ranges (H ∈ [0,180], S/V ∈ [0,255]) ───────────────
    _GREEN_H_LOW    = np.array([ 40,  80,  60], dtype=np.uint8)   # TL triangle
    _GREEN_H_HIGH   = np.array([ 85, 255, 255], dtype=np.uint8)
    _RED1_LOW       = np.array([  0, 100,  60], dtype=np.uint8)   # BR rectangle
    _RED1_HIGH      = np.array([ 10, 255, 255], dtype=np.uint8)
    _RED2_LOW       = np.array([165, 100,  60], dtype=np.uint8)
    _RED2_HIGH      = np.array([180, 255, 255], dtype=np.uint8)
    _BLUE_H_LOW     = np.array([100,  80,  60], dtype=np.uint8)   # TR circle
    _BLUE_H_HIGH    = np.array([130, 255, 255], dtype=np.uint8)
    _YELLOW_H_LOW   = np.array([ 20, 100,  60], dtype=np.uint8)   # BL diamond
    _YELLOW_H_HIGH  = np.array([ 35, 255, 255], dtype=np.uint8)

    # ── Detection geometry ────────────────────────────────────────────────────
    _MIN_CONTOUR_AREA       = 200
    _MAX_CONTOUR_AREA_RATIO = 0.30
    _APPROX_EPSILON_RATIO   = 0.03
    _EDGE_SNAP_TOLERANCE_PX = 5

    # ── EMA / stability ───────────────────────────────────────────────────────
    _EMA_ALPHA               = 0.35     # corner position EMA
    _H_EMA_ALPHA             = 0.20     # homography matrix EMA (slower)
    _LOCK_CONFIDENCE_MIN     = 0.45
    _STABLE_FRAMES_REQUIRED  = 3

    # ── Zhang multi-frame accumulation ────────────────────────────────────────
    _ZHANG_MIN_OBSERVATIONS = 10   # frames needed before computing H
    _ZHANG_MAX_OBSERVATIONS = 50   # ring-buffer cap
    _ZHANG_REPROJ_THRESHOLD = 5.0  # RANSAC reprojection threshold (px)

    def __init__(
        self,
        camera_matrix:    Optional[np.ndarray] = None,
        dist_coeffs:      Optional[np.ndarray] = None,
        calibration_file: Optional[str]        = None,
    ):
        # Optional camera intrinsics for lens undistortion
        self._K:    Optional[np.ndarray] = camera_matrix
        self._dist: Optional[np.ndarray] = dist_coeffs
        if calibration_file:
            self._load_camera_calibration(calibration_file)

        self._result        = CalibrationResult()
        self._ema_corners   = {}          # {'TL':(x,y), 'TR':…, 'BR':…, 'BL':…}
        self._stable_count  = 0
        self._frame_w       = 1
        self._frame_h       = 1
        self._ema_H: Optional[np.ndarray] = None

        # Zhang observation ring-buffer — each entry is a dict:
        #   {'TL': (x,y)|None, 'TR': (x,y)|None,
        #    'BR': (x,y)|None, 'BL': (x,y)|None}
        self._observations: deque = deque(maxlen=self._ZHANG_MAX_OBSERVATIONS)

        self._threshold_var  = _PlainVar(150)
        self._use_hsv_var    = _PlainVar(True)
        self._show_debug_var = _PlainVar(False)
        self._status_var     = _PlainVar("Not calibrated")

    # ── Camera calibration file loader ────────────────────────────────────────

    def _load_camera_calibration(self, path: str):
        """
        Load K and dist_coeffs from a JSON or OpenCV YAML file.

        JSON schema expected:
            {
                "camera_matrix": [[fx,0,cx],[0,fy,cy],[0,0,1]],
                "dist_coeffs":   [k1, k2, p1, p2, k3]
            }
        """
        if not os.path.isfile(path):
            print(f"CALIB  warning=calibration_file_not_found path={path!r}")
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in (".yml", ".yaml", ".xml"):
                fs = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
                K  = fs.getNode("camera_matrix").mat()
                d  = fs.getNode("dist_coeffs").mat()
                fs.release()
                if K is not None and K.shape == (3, 3):
                    self._K    = K.astype(np.float64)
                    self._dist = d.astype(np.float64) if d is not None else None
                    print(f"CALIB  loaded_opencv_yaml path={path!r}")
                else:
                    print(f"CALIB  warning=invalid_opencv_yaml path={path!r}")
            else:  # JSON
                with open(path) as f:
                    data = json.load(f)
                K = np.array(data["camera_matrix"], dtype=np.float64)
                d = np.array(data["dist_coeffs"],   dtype=np.float64).flatten()
                if K.shape == (3, 3):
                    self._K    = K
                    self._dist = d
                    print(f"CALIB  loaded_json path={path!r}")
                else:
                    print(f"CALIB  warning=invalid_json_matrix path={path!r}")
        except Exception as exc:
            print(f"CALIB  warning=load_failed path={path!r} err={exc}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_projected_bbox(self) -> Tuple[int, int, int, int]:
        return self._result.as_bbox()

    def get_result(self) -> CalibrationResult:
        return self._result

    def reset(self):
        self._result       = CalibrationResult()
        self._ema_corners  = {}
        self._stable_count = 0
        self._ema_H        = None
        self._observations.clear()
        self._status_var.set("Not calibrated")

    # ── Main calibration entry point ──────────────────────────────────────────

    def calibrate_projector(self, webcam_image: np.ndarray) -> np.ndarray:
        """
        Process one camera frame.  Updates internal state and returns an
        annotated copy of the frame for optional preview display.
        """
        if webcam_image is None or webcam_image.size == 0:
            return webcam_image

        frame = webcam_image.copy()
        self._frame_h, self._frame_w = frame.shape[:2]
        max_area = self._frame_w * self._frame_h * self._MAX_CONTOUR_AREA_RATIO

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # ── 1. Detect all four markers ─────────────────────────────────────
        markers = self._detect_all_markers(frame, hsv, max_area)
        # markers: dict  key → (anchor_xy, contour, confidence)
        #          keys: 'TL', 'TR', 'BR', 'BL'

        # ── 2. Update EMA corner positions ────────────────────────────────
        for key, (anchor, _, _) in markers.items():
            if anchor is not None:
                if key not in self._ema_corners:
                    self._ema_corners[key] = np.array(anchor, dtype=np.float32)
                else:
                    a = self._EMA_ALPHA
                    self._ema_corners[key] = (
                        a * np.array(anchor, dtype=np.float32)
                        + (1 - a) * self._ema_corners[key]
                    )

        # ── 3. Store observation for Zhang accumulation ────────────────────
        obs = {k: (tuple(self._ema_corners[k]) if k in self._ema_corners
                   else None)
               for k in ("TL", "TR", "BR", "BL")}
        has_tl = obs["TL"] is not None
        has_br = obs["BR"] is not None
        if has_tl and has_br:
            self._observations.append(obs)

        # ── 4. Compute calibration when enough data is available ───────────
        n_obs = len(self._observations)
        if n_obs >= self._ZHANG_MIN_OBSERVATIONS and has_tl and has_br:
            self._try_compute_zhang()
        elif has_tl and has_br and not self._result.locked:
            # Not enough obs yet — provisional bbox from EMA corners
            self._update_provisional_bbox()

        # ── 5. Stability gating ────────────────────────────────────────────
        if self._result.locked:
            self._stable_count = min(
                self._stable_count + 1, self._STABLE_FRAMES_REQUIRED)
        else:
            self._stable_count = max(self._stable_count - 1, 0)

        # ── 6. Update status string ────────────────────────────────────────
        self._update_status(n_obs, markers)

        # ── 7. Draw annotation ────────────────────────────────────────────
        if self._show_debug_var.get():
            frame = self._draw_debug(frame, markers)
        else:
            frame = self._draw_minimal(frame, markers)

        return frame

    # ── All-marker detector ───────────────────────────────────────────────────

    def _detect_all_markers(
        self,
        frame:    np.ndarray,
        hsv:      np.ndarray,
        max_area: float,
    ) -> Dict[str, Tuple]:
        """
        Returns dict: marker_key → (anchor_xy_or_None, contour_or_None, conf)
        """
        results = {}

        # TL — Green Triangle (top-left quadrant)
        cnt, conf, anchor = self._detect_shape(
            frame, hsv, max_area,
            colour_masks = [cv2.inRange(hsv, self._GREEN_H_LOW, self._GREEN_H_HIGH)],
            quadrant     = "top_left",
            n_vertices   = 3,
            corner_fn    = self._top_left_coord,
            confidence_fn= self._triangle_confidence,
        )
        results["TL"] = (anchor, cnt, conf)

        # BR — Red Rectangle (bottom-right quadrant)
        red_mask = cv2.bitwise_or(
            cv2.inRange(hsv, self._RED1_LOW,  self._RED1_HIGH),
            cv2.inRange(hsv, self._RED2_LOW,  self._RED2_HIGH),
        )
        cnt, conf, anchor = self._detect_shape(
            frame, hsv, max_area,
            colour_masks = [red_mask],
            quadrant     = "bottom_right",
            n_vertices   = 4,
            corner_fn    = self._bottom_right_coord,
            confidence_fn= self._rect_confidence,
        )
        results["BR"] = (anchor, cnt, conf)

        # TR — Blue Circle (top-right quadrant)
        cnt, conf, anchor = self._detect_shape(
            frame, hsv, max_area,
            colour_masks = [cv2.inRange(hsv, self._BLUE_H_LOW, self._BLUE_H_HIGH)],
            quadrant     = "top_right",
            n_vertices   = None,   # circle: any vertex count, checked via circularity
            corner_fn    = self._top_right_coord,
            confidence_fn= self._circle_confidence,
            is_circle    = True,
        )
        results["TR"] = (anchor, cnt, conf)

        # BL — Yellow Diamond (bottom-left quadrant)
        cnt, conf, anchor = self._detect_shape(
            frame, hsv, max_area,
            colour_masks = [cv2.inRange(hsv, self._YELLOW_H_LOW, self._YELLOW_H_HIGH)],
            quadrant     = "bottom_left",
            n_vertices   = 4,
            corner_fn    = self._bottom_left_coord,
            confidence_fn= self._diamond_confidence,
        )
        results["BL"] = (anchor, cnt, conf)

        return results

    # ── Generic shape detector ────────────────────────────────────────────────

    def _detect_shape(
        self,
        frame, hsv, max_area,
        colour_masks, quadrant, n_vertices, corner_fn, confidence_fn,
        is_circle=False,
    ):
        """Unified contour-detection pipeline for any marker shape."""
        combined_mask = colour_masks[0].copy()
        for m in colour_masks[1:]:
            combined_mask = cv2.bitwise_or(combined_mask, m)

        combined_mask = self._apply_quadrant_mask(combined_mask, quadrant)
        combined_mask = self._clean_mask(combined_mask)

        # HSV fallback to Otsu grayscale
        if not self._use_hsv_var.get() or cv2.countNonZero(combined_mask) == 0:
            combined_mask = self._clean_mask(
                self._grayscale_fallback_mask(frame, quadrant))

        contours, _ = cv2.findContours(
            combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_cnt = best_anchor = None
        best_conf = 0.0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self._MIN_CONTOUR_AREA or area > max_area:
                continue

            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, self._APPROX_EPSILON_RATIO * peri, True)
            circ   = self._circularity(area, peri)

            if is_circle:
                # Accept highly circular blobs regardless of approx vertex count
                if circ < 0.60:
                    continue
            else:
                if n_vertices is not None and len(approx) != n_vertices:
                    continue

            conf = confidence_fn(approx, area, circ, combined_mask)
            if conf > best_conf:
                best_cnt   = approx
                best_conf  = conf
                best_anchor = np.array(
                    corner_fn(approx if not is_circle else cnt),
                    dtype=np.float32)

        # Edge-snap
        if best_anchor is not None:
            best_anchor = self._snap_anchor(best_anchor, quadrant)

        return best_cnt, best_conf, best_anchor

    # ── Zhang's method core ───────────────────────────────────────────────────

    def _try_compute_zhang(self):
        """
        Fit a perspective homography from accumulated observations using
        RANSAC — the Zhang multi-view robustness principle applied to
        multi-frame temporal observations.

        Four-marker path (full perspective H):
            source points = detected marker positions in camera pixels
            destination   = unit-square corners [0,1]²

        Two-marker fallback (affine H via getPerspectiveTransform):
            uses only TL and BR, adds synthetic TR and BL from the EMA
            bbox to construct a minimal 4-point affine approximation.
        """
        four_marker_obs = [
            obs for obs in self._observations
            if all(obs[k] is not None for k in ("TL", "TR", "BR", "BL"))
        ]
        two_marker_obs  = [
            obs for obs in self._observations
            if obs["TL"] is not None and obs["BR"] is not None
        ]

        use_four = len(four_marker_obs) >= max(4, self._ZHANG_MIN_OBSERVATIONS // 2)

        if use_four:
            src_pts, dst_pts, marker_count = \
                self._build_zhang_correspondences_4(four_marker_obs)
        else:
            src_pts, dst_pts, marker_count = \
                self._build_zhang_correspondences_2(two_marker_obs)

        if src_pts is None or len(src_pts) < 4:
            return

        # Undistort source points with camera intrinsics when available
        src_pts_ud = self._undistort_points(src_pts)

        # findHomography with RANSAC — works on all accumulated point pairs
        H, mask = cv2.findHomography(
            src_pts_ud, dst_pts,
            method           = cv2.RANSAC,
            ransacReprojThreshold = self._ZHANG_REPROJ_THRESHOLD,
        )

        if H is None:
            print("CALIB  warning=homography_failed  "
                  f"n_src={len(src_pts)}")
            return

        # Reprojection error on inliers
        reproj_err = self._compute_reproj_error(src_pts_ud, dst_pts, H, mask)

        # EMA smoothing of H
        if self._ema_H is None:
            self._ema_H = H.copy()
        else:
            a = self._H_EMA_ALPHA
            self._ema_H = a * H + (1 - a) * self._ema_H

        # Derive legacy bbox from corners of the unit square warped back
        corners_cam = self._bbox_from_homography(self._ema_H)
        if corners_cam is None:
            return

        tl, tr, br, bl = corners_cam
        top_x    = int(round(min(tl[0], bl[0])))
        top_y    = int(round(min(tl[1], tr[1])))
        bottom_x = int(round(max(tr[0], br[0])))
        bottom_y = int(round(max(bl[1], br[1])))

        if bottom_x <= top_x or bottom_y <= top_y:
            return

        # Compute confidence from inlier ratio
        inlier_ratio = float(mask.sum()) / float(len(mask)) if mask is not None else 0.5
        confidence   = round(min(inlier_ratio, 1.0), 3)

        self._result = CalibrationResult(
            top_x        = top_x,
            top_y        = top_y,
            bottom_x     = bottom_x,
            bottom_y     = bottom_y,
            confidence   = confidence,
            locked       = confidence >= self._LOCK_CONFIDENCE_MIN,
            homography   = self._ema_H.copy(),
            corners_px   = np.array([tl, tr, br, bl], dtype=np.float32),
            marker_count = marker_count,
            reproj_error = reproj_err,
        )
        self._stable_count = min(
            self._stable_count + 1, self._STABLE_FRAMES_REQUIRED)

    def _build_zhang_correspondences_4(
        self, obs_list: List[Dict]
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], int]:
        """
        Build (src, dst) point arrays from 4-marker observations.
        Each observation contributes 4 correspondences → RANSAC has
        many rows to work with, matching Zhang's over-determined system.
        """
        src, dst = [], []
        for obs in obs_list:
            for key, dst_pt in zip(
                ("TL", "TR", "BR", "BL"),
                _ZHANG_DST,
            ):
                pt = obs[key]
                if pt is not None:
                    src.append(pt)
                    dst.append(dst_pt)

        if not src:
            return None, None, 0

        return (
            np.array(src, dtype=np.float32).reshape(-1, 1, 2),
            np.array(dst, dtype=np.float32).reshape(-1, 1, 2),
            4,
        )

    def _build_zhang_correspondences_2(
        self, obs_list: List[Dict]
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], int]:
        """
        Fallback: only TL and BR detected.  Synthesise TR and BL from
        bbox geometry so findHomography always receives 4 corner types.
        This is an affine approximation — perspective distortion is
        uncompensated but the result is identical to the legacy bbox.
        """
        tl_pts = [obs["TL"] for obs in obs_list if obs["TL"] is not None]
        br_pts = [obs["BR"] for obs in obs_list if obs["BR"] is not None]

        if not tl_pts or not br_pts:
            return None, None, 0

        tl = np.median(tl_pts, axis=0)
        br = np.median(br_pts, axis=0)
        tr = np.array([br[0], tl[1]], dtype=np.float32)
        bl = np.array([tl[0], br[1]], dtype=np.float32)

        src = np.array([[tl], [tr], [br], [bl]], dtype=np.float32)
        dst = _ZHANG_DST.reshape(-1, 1, 2).copy()
        return src, dst, 2

    def _undistort_points(self, pts: np.ndarray) -> np.ndarray:
        """
        Apply camera intrinsic undistortion (Zhang's calibration step).
        If no intrinsics are loaded, returns pts unchanged.
        """
        if self._K is None or self._dist is None:
            return pts
        try:
            undistorted = cv2.undistortPoints(
                pts.reshape(-1, 1, 2).astype(np.float64),
                self._K, self._dist,
                P=self._K,   # re-project to original pixel space
            )
            return undistorted.astype(np.float32).reshape(-1, 1, 2)
        except cv2.error as exc:
            print(f"CALIB  warning=undistort_failed err={exc}")
            return pts

    @staticmethod
    def _compute_reproj_error(
        src: np.ndarray, dst: np.ndarray,
        H:   np.ndarray, mask: Optional[np.ndarray],
    ) -> float:
        """Mean reprojection error on inlier points (pixels)."""
        try:
            projected = cv2.perspectiveTransform(
                src.reshape(-1, 1, 2).astype(np.float32), H)
            diff = projected.reshape(-1, 2) - dst.reshape(-1, 2)
            err  = np.linalg.norm(diff, axis=1)
            if mask is not None:
                inlier_mask = mask.flatten().astype(bool)
                if inlier_mask.any():
                    err = err[inlier_mask]
            return float(np.mean(err))
        except Exception:
            return 0.0

    @staticmethod
    def _bbox_from_homography(H: np.ndarray
                              ) -> Optional[List[Tuple[float, float]]]:
        """
        Invert H (arena [0,1]² → camera pixels) and evaluate at the
        four unit-square corners to recover camera-space corners.
        """
        try:
            H_inv = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            return None
        corners_norm = np.array(
            [[[0.0, 0.0]], [[1.0, 0.0]], [[1.0, 1.0]], [[0.0, 1.0]]],
            dtype=np.float32)
        cam = cv2.perspectiveTransform(corners_norm, H_inv).reshape(-1, 2)
        return [tuple(p) for p in cam]   # TL, TR, BR, BL

    def _update_provisional_bbox(self):
        """Pre-lock bbox from EMA corners while Zhang is still accumulating."""
        tl = self._ema_corners.get("TL")
        br = self._ema_corners.get("BR")
        if tl is None or br is None:
            return
        self._result = CalibrationResult(
            top_x    = int(round(tl[0])),
            top_y    = int(round(tl[1])),
            bottom_x = int(round(br[0])),
            bottom_y = int(round(br[1])),
            confidence   = 0.0,
            locked       = False,
            marker_count = len(self._ema_corners),
        )

    # ── Status string ─────────────────────────────────────────────────────────

    def _update_status(self, n_obs: int, markers: Dict):
        detected = [k for k, (a, _, _) in markers.items() if a is not None]
        if self._result.locked:
            mode = "4-pt homography" if self._result.marker_count == 4 else "2-pt affine"
            self._status_var.set(
                f"Locked ✓  {self._result.width()}×{self._result.height()} px"
                f"  conf={self._result.confidence:.2f}"
                f"  reproj={self._result.reproj_error:.1f}px"
                f"  [{mode}]"
            )
        else:
            self._status_var.set(
                f"Accumulating… obs={n_obs}/{self._ZHANG_MIN_OBSERVATIONS}"
                f"  detected={detected}"
                f"  stable={self._stable_count}/{self._STABLE_FRAMES_REQUIRED}"
            )

    # ── Shape detectors (confidence scorers) ──────────────────────────────────

    def _triangle_confidence(self, approx, area, circularity, mask) -> float:
        score  = min(circularity / 0.605, 1.0) * 0.3
        score += self._mask_fill_ratio(approx, mask) * 0.4
        angles = self._polygon_angles(approx)
        score += (1.0 - min(np.std(angles) / 60.0, 1.0)) * 0.3
        return min(score, 1.0)

    def _rect_confidence(self, approx, area, circularity, mask) -> float:
        score  = min(circularity / 0.785, 1.0) * 0.25
        score += self._mask_fill_ratio(approx, mask) * 0.45
        angles = self._polygon_angles(approx)
        score += (1.0 - min(np.std(angles) / 90.0, 1.0)) * 0.30
        return min(score, 1.0)

    def _circle_confidence(self, approx, area, circularity, mask) -> float:
        """Circles are scored purely on circularity and mask fill."""
        score  = min(circularity / 1.0, 1.0) * 0.55
        score += self._mask_fill_ratio(approx, mask) * 0.45
        return min(score, 1.0)

    def _diamond_confidence(self, approx, area, circularity, mask) -> float:
        """
        Diamond (rotated square): 4 vertices, angles near 90°, but the
        shape is rotated ~45° so the aspect ratio of the bounding box
        should be roughly 1:1.
        """
        if len(approx) != 4:
            return 0.0
        score  = min(circularity / 0.785, 1.0) * 0.20
        score += self._mask_fill_ratio(approx, mask) * 0.45
        angles = self._polygon_angles(approx)
        score += (1.0 - min(np.std(angles) / 90.0, 1.0)) * 0.25
        # Bonus: bounding box should be roughly square for a diamond
        x, y, w, h = cv2.boundingRect(approx)
        aspect = min(w, h) / max(max(w, h), 1)
        score += aspect * 0.10
        return min(score, 1.0)

    # ── Corner coordinate extractors ──────────────────────────────────────────

    @staticmethod
    def _top_left_coord(cnt: np.ndarray) -> Tuple[int, int]:
        pts = cnt.reshape(-1, 2)
        idx = np.argmin(pts[:, 0] + pts[:, 1])
        return int(pts[idx, 0]), int(pts[idx, 1])

    @staticmethod
    def _top_right_coord(cnt: np.ndarray) -> Tuple[int, int]:
        pts = cnt.reshape(-1, 2)
        idx = np.argmin(-pts[:, 0] + pts[:, 1])
        return int(pts[idx, 0]), int(pts[idx, 1])

    @staticmethod
    def _bottom_right_coord(cnt: np.ndarray) -> Tuple[int, int]:
        pts = cnt.reshape(-1, 2)
        idx = np.argmax(pts[:, 0] + pts[:, 1])
        return int(pts[idx, 0]), int(pts[idx, 1])

    @staticmethod
    def _bottom_left_coord(cnt: np.ndarray) -> Tuple[int, int]:
        pts = cnt.reshape(-1, 2)
        idx = np.argmin(pts[:, 0] - pts[:, 1])
        return int(pts[idx, 0]), int(pts[idx, 1])

    # ── Geometry utilities ────────────────────────────────────────────────────

    def _quadrant_mask(self, quadrant: str) -> np.ndarray:
        mask  = np.zeros((self._frame_h, self._frame_w), dtype=np.uint8)
        mid_x = self._frame_w // 2
        mid_y = self._frame_h // 2
        qmap  = {
            "top_left":     (slice(None, mid_y), slice(None, mid_x)),
            "top_right":    (slice(None, mid_y), slice(mid_x, None)),
            "bottom_right": (slice(mid_y, None), slice(mid_x, None)),
            "bottom_left":  (slice(mid_y, None), slice(None, mid_x)),
        }
        if quadrant not in qmap:
            raise ValueError(f"Unknown quadrant: {quadrant!r}")
        rows, cols = qmap[quadrant]
        mask[rows, cols] = 255
        return mask

    def _apply_quadrant_mask(self, mask: np.ndarray, quadrant: str) -> np.ndarray:
        return cv2.bitwise_and(mask, self._quadrant_mask(quadrant))

    def _grayscale_fallback_mask(self, frame: np.ndarray, quadrant: str) -> np.ndarray:
        grey    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi_q   = self._quadrant_mask(quadrant)
        _, otsu = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        otsu    = cv2.bitwise_and(otsu, roi_q)
        if cv2.countNonZero(otsu) > 0:
            return otsu
        _, manual = cv2.threshold(grey, self._threshold_var.get(), 255, cv2.THRESH_BINARY)
        return cv2.bitwise_and(manual, roi_q)

    @staticmethod
    def _circularity(area: float, perimeter: float) -> float:
        if perimeter == 0:
            return 0.0
        return 4 * math.pi * area / (perimeter ** 2)

    @staticmethod
    def _polygon_angles(approx: np.ndarray) -> np.ndarray:
        pts = approx.reshape(-1, 2).astype(np.float32)
        n   = len(pts)
        angles = []
        for i in range(n):
            a = pts[(i - 1) % n]; b = pts[i]; c = pts[(i + 1) % n]
            ba = a - b; bc = c - b
            cos_a = np.dot(ba, bc) / (
                np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
            angles.append(math.degrees(
                math.acos(float(np.clip(cos_a, -1, 1)))))
        return np.array(angles)

    def _mask_fill_ratio(self, approx: np.ndarray, mask: np.ndarray) -> float:
        tmp = np.zeros(mask.shape, dtype=np.uint8)
        cv2.fillPoly(tmp, [approx], 255)
        total = tmp.sum() / 255
        if total == 0:
            return 0.0
        white = cv2.bitwise_and(mask, tmp).sum() / 255
        return float(white / total)

    @staticmethod
    def _clean_mask(mask: np.ndarray) -> np.ndarray:
        k      = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=1)
        return  cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k, iterations=2)

    def _snap_anchor(self, pt: np.ndarray, quadrant: str) -> np.ndarray:
        """Snap near-edge anchors to the frame boundary."""
        snapped = np.array(pt, dtype=np.float32, copy=True).reshape(2)
        max_x   = float(max(self._frame_w - 1, 0))
        max_y   = float(max(self._frame_h - 1, 0))
        t       = self._EDGE_SNAP_TOLERANCE_PX
        snapped[0] = float(np.clip(snapped[0], 0, max_x))
        snapped[1] = float(np.clip(snapped[1], 0, max_y))
        if "left"  in quadrant and snapped[0] <= t:        snapped[0] = 0.0
        if "right" in quadrant and snapped[0] >= max_x-t:  snapped[0] = max_x
        if "top"   in quadrant and snapped[1] <= t:        snapped[1] = 0.0
        if "bottom"in quadrant and snapped[1] >= max_y-t:  snapped[1] = max_y
        return snapped

    # ── Drawing helpers ───────────────────────────────────────────────────────

    _MARKER_COLORS = {
        "TL": (0, 255,   0),   # green
        "TR": (255, 0,   0),   # blue
        "BR": (0,   0, 255),   # red
        "BL": (0, 255, 255),   # yellow
    }
    _MARKER_LABELS = {"TL": "TL▲", "TR": "TR●", "BR": "BR■", "BL": "BL◆"}

    def _draw_minimal(self, frame: np.ndarray, markers: Dict) -> np.ndarray:
        for key, (anchor, _, _) in markers.items():
            if anchor is not None:
                cv2.circle(frame,
                           (int(anchor[0]), int(anchor[1])),
                           8, self._MARKER_COLORS[key], -1)
        if self._result.valid:
            if self._result.corners_px is not None:
                pts = self._result.corners_px.astype(np.int32).reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], True, (0, 255, 255), 2)
            else:
                cv2.rectangle(frame,
                              (self._result.top_x,    self._result.top_y),
                              (self._result.bottom_x, self._result.bottom_y),
                              (0, 255, 255), 2)
        return frame

    def _draw_debug(self, frame: np.ndarray, markers: Dict) -> np.ndarray:
        overlay = frame.copy()
        for key, (anchor, cnt, conf) in markers.items():
            if cnt is not None:
                cv2.drawContours(overlay, [cnt], 0, self._MARKER_COLORS[key], -1)
        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

        font = cv2.FONT_HERSHEY_SIMPLEX
        for key, (anchor, _, conf) in markers.items():
            if anchor is None:
                continue
            ax, ay = int(anchor[0]), int(anchor[1])
            col    = self._MARKER_COLORS[key]
            cv2.circle(frame, (ax, ay), 7, col, -1)
            cv2.putText(frame,
                        f"{self._MARKER_LABELS[key]} ({ax},{ay}) c={conf:.2f}",
                        (ax + 8, ay - 8), font, 0.42, col, 1, cv2.LINE_AA)

        if self._result.valid:
            if self._result.corners_px is not None:
                pts = self._result.corners_px.astype(np.int32).reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], True, (0, 255, 255), 2)
            else:
                cv2.rectangle(frame,
                              (self._result.top_x,    self._result.top_y),
                              (self._result.bottom_x, self._result.bottom_y),
                              (0, 255, 255), 2)
            cv2.putText(frame,
                        f"{self._result.width()}×{self._result.height()}px "
                        f"reproj={self._result.reproj_error:.1f}px",
                        (self._result.top_x + 4, self._result.top_y - 6),
                        font, 0.48, (0, 255, 255), 1, cv2.LINE_AA)

        # Observation progress bar
        pct   = min(len(self._observations) / self._ZHANG_MIN_OBSERVATIONS, 1.0)
        bar_w = int(self._frame_w * pct)
        cv2.rectangle(frame, (0, 0), (bar_w, 8),
                      (0, 255, 0) if self._result.locked else (0, 165, 255), -1)
        mode_lbl = (f"markers={self._result.marker_count}"
                    if self._result.locked else
                    f"obs={len(self._observations)}/{self._ZHANG_MIN_OBSERVATIONS}")
        cv2.putText(frame,
                    f"stable {self._stable_count}/{self._STABLE_FRAMES_REQUIRED}  "
                    f"conf {self._result.confidence:.2f}  {mode_lbl}",
                    (8, 22), font, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
        return frame


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Shot detector  (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════

class Pixel:
    __slots__ = ("x", "y", "color", "current_lum", "lum_average",
                 "color_average", "connectedness")

    def __init__(self, x, y, color=0, current_lum=0,
                 lum_average=0, color_average=0):
        self.x             = int(x)
        self.y             = int(y)
        self.color         = color
        self.current_lum   = current_lum
        self.lum_average   = lum_average
        self.color_average = color_average
        self.connectedness = 0

    def __hash__(self):  return hash((self.x, self.y))
    def __eq__(self, o): return isinstance(o, Pixel) and self.x == o.x and self.y == o.y


class PixelCluster(set):
    CURRENT_COLOR_BIAS_MULTIPLIER = 0.8
    MAXIMUM_CONNECTEDNESS         = 8

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.center_pixel_x:   float = 0.0
        self.center_pixel_y:   float = 0.0
        self.color_confidence: float = 0.0

    def get_color_difference(self, working_frame_hsv, color_distance_from_red):
        rows, cols = working_frame_hsv.shape[:2]
        visited: Dict[Tuple[int, int], np.ndarray] = {}

        for pixel in self:
            if pixel.connectedness >= self.MAXIMUM_CONNECTEDNESS:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    rx, ry = pixel.x + dx, pixel.y + dy
                    if 0 <= rx < cols and 0 <= ry < rows:
                        key = (rx, ry)
                        if key not in visited:
                            visited[key] = working_frame_hsv[ry, rx]

        if not visited:
            return 0

        vals  = np.array(list(visited.values()), dtype=np.int32)
        h_arr = vals[:, 0]; s_arr = vals[:, 1]; v_arr = vals[:, 2]
        avg_s = int(np.mean(s_arr)); avg_v = int(np.mean(v_arr))

        useful_mask = (s_arr > avg_s) & (v_arr < avg_v)
        if not np.any(useful_mask):
            return 0

        h_u = h_arr[useful_mask]; s_u = s_arr[useful_mask]; v_u = v_arr[useful_mask]
        weight     = (s_u * v_u).astype(np.float32)
        weight_sum = weight.sum()
        if weight_sum == 0:
            return 0

        d_from_red   = np.minimum(h_u, np.abs(180 - h_u)) * s_u * v_u
        d_from_green = np.abs(60 - h_u) * s_u * v_u
        current_col  = (d_from_red - d_from_green).astype(np.float32)

        all_keys  = list(visited.keys())
        bias_vals = np.array(
            [color_distance_from_red[ry, rx] for (rx, ry) in all_keys],
            dtype=np.float32,
        )[useful_mask]

        col_distance_arr = current_col - self.CURRENT_COLOR_BIAS_MULTIPLIER * bias_vals
        color_distance   = float(np.sum(col_distance_arr * weight) / weight_sum)
        self.color_confidence = min(abs(color_distance) / 5000.0, 1.0)
        return int(color_distance)

    def get_color(self, working_frame_hsv, color_distance_from_red):
        color_dist = self.get_color_difference(working_frame_hsv, color_distance_from_red)
        return "RED" if color_dist < 1000 else "GREEN"


class PixelClusterManager:
    MINIMUM_CONNECTEDNESS        = 3.66
    MAXIMUM_CONNECTEDNESS_SCALE  = 6.0
    MINIMUM_CONNECTEDNESS_FACTOR = 0.018
    MINIMUM_DENSITY              = 0.69
    MINIMUM_SHOT_RATIO           = 0.5
    MAXIMUM_SHOT_RATIO           = 1.43
    SMALL_SHOT_THRESHOLD         = 16
    MINIMUM_SHOT_RATIO_SMALL     = 0.47
    MAXIMUM_SHOT_RATIO_SMALL     = 1.75
    EXCESSIVE_PIXEL_CUTOFF       = 300
    EXCESSIVE_PIXEL_REGION_COUNT = 1

    def __init__(self, feed_width: int, feed_height: int):
        self.feed_width  = feed_width
        self.feed_height = feed_height

    def _preprocess(self, pixel_set, pixel_mapping):
        stack             = []
        number_of_regions = -1
        too_many          = len(pixel_set) > self.EXCESSIVE_PIXEL_CUTOFF

        for key, pixel in pixel_set.items():
            if pixel in pixel_mapping:
                continue
            number_of_regions += 1
            stack.append(pixel)
            pixel_mapping[pixel] = number_of_regions

            if too_many and number_of_regions > self.EXCESSIVE_PIXEL_REGION_COUNT:
                break

            while stack:
                pt   = stack.pop()
                conn = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        nx, ny = pt.x + dx, pt.y + dy
                        if not (0 <= nx < self.feed_width and
                                0 <= ny < self.feed_height):
                            continue
                        nbr_key = (nx, ny)
                        if nbr_key in pixel_set:
                            nbr = pixel_set[nbr_key]
                            if nbr not in pixel_mapping:
                                stack.append(nbr)
                                pixel_mapping[nbr] = number_of_regions
                            conn += 1
                pt.connectedness = conn

        return number_of_regions

    def cluster_pixels(self, clusterable_pixels, minimum_shot_dimension):
        pixel_set = {(p.x, p.y): p for p in clusterable_pixels}
        if not pixel_set:
            return []

        pixel_mapping = {}
        n_regions = self._preprocess(pixel_set, pixel_mapping)

        clusters = []
        for region_id in range(n_regions + 1):
            cluster = PixelCluster()
            sum_wx = sum_wy = avg_conn = 0.0
            min_x = self.feed_width;  min_y = self.feed_height
            max_x = max_y = 0

            for pixel, rid in pixel_mapping.items():
                if rid != region_id:
                    continue
                min_x = min(min_x, pixel.x); max_x = max(max_x, pixel.x)
                min_y = min(min_y, pixel.y); max_y = max(max_y, pixel.y)
                cluster.add(pixel)
                c        = pixel.connectedness
                sum_wx  += pixel.x * c
                sum_wy  += pixel.y * c
                avg_conn += c

            sz = len(cluster)
            if sz < minimum_shot_dimension or avg_conn == 0:
                continue

            cx        = sum_wx / avg_conn
            cy        = sum_wy / avg_conn
            avg_conn /= sz

            scaled_min = min(
                self.MINIMUM_CONNECTEDNESS
                + (sz - minimum_shot_dimension) * self.MINIMUM_CONNECTEDNESS_FACTOR,
                self.MAXIMUM_CONNECTEDNESS_SCALE,
            )
            if avg_conn < scaled_min:
                continue

            sw    = (max_x - min_x) + 1
            sh    = (max_y - min_y) + 1
            ratio = sw / sh

            if (sw + sh) > self.SMALL_SHOT_THRESHOLD:
                if not (self.MINIMUM_SHOT_RATIO <= ratio <= self.MAXIMUM_SHOT_RATIO):
                    continue
            else:
                if not (self.MINIMUM_SHOT_RATIO_SMALL <= ratio <= self.MAXIMUM_SHOT_RATIO_SMALL):
                    continue

            r       = (sw + sh) / 4.0
            density = sz / (math.pi * r * r)
            if density < self.MINIMUM_DENSITY:
                continue

            cluster.center_pixel_x = cx
            cluster.center_pixel_y = cy
            clusters.append(cluster)

        return clusters


class ShotDeduplicator:
    def __init__(self, radius_px: float = 20.0, cooldown_s: float = 0.4):
        self.radius_px  = radius_px
        self.cooldown_s = cooldown_s
        self._history: List[Dict] = []

    def is_duplicate(self, x: float, y: float) -> bool:
        now = time.monotonic()
        self._history = [h for h in self._history
                         if now - h["t"] < self.cooldown_s]
        for h in self._history:
            if math.hypot(x - h["x"], y - h["y"]) < self.radius_px:
                return True
        self._history.append({"x": x, "y": y, "t": now})
        return False

    def reset(self):
        self._history.clear()


class JavaShotDetector:
    def __init__(
        self,
        feed_width:  int,
        feed_height: int,
        luminance_mode:             str   = "combined",
        brightness_increase_ratio:  float = 0.10,
        excessive_brightness_ratio: float = 0.96,
        use_dynamic_threshold:      bool  = True,
        max_dynamic_ratio:          float = 0.25,
        use_variance_threshold:     bool  = True,
        variance_alpha:             float = 0.05,
        variance_k:                 float = 2.5,
        use_temporal_filter:        bool  = True,
        temporal_window:            int   = 3,
        temporal_min_frames:        int   = 1,
        use_excessive_mask:         bool  = True,
        min_shot_dimension:         Optional[int] = None,
        dedup_radius_px:            float = 20.0,
        dedup_cooldown_s:           float = 0.40,
        roi_mask:                   Optional[np.ndarray] = None,
    ):
        self.feed_width  = feed_width
        self.feed_height = feed_height

        self.pixel_cluster_manager = PixelClusterManager(feed_width, feed_height)
        self.deduplicator          = ShotDeduplicator(dedup_radius_px, dedup_cooldown_s)

        self.luminance_mode         = luminance_mode
        self.use_dynamic_threshold  = use_dynamic_threshold
        self.max_dynamic_ratio      = max_dynamic_ratio
        self.use_variance_threshold = use_variance_threshold
        self.variance_alpha         = variance_alpha
        self.variance_k             = variance_k
        self.use_temporal_filter    = use_temporal_filter
        self.temporal_window        = temporal_window
        self.temporal_min_frames    = temporal_min_frames
        self.use_excessive_mask     = use_excessive_mask
        self.roi_mask               = roi_mask

        self.MAXIMUM_LUM_VALUE              = 65280
        self.EXCESSIVE_BRIGHTNESS_THRESHOLD = int(
            excessive_brightness_ratio * self.MAXIMUM_LUM_VALUE)
        self.MINIMUM_BRIGHTNESS_INCREASE    = int(
            brightness_increase_ratio   * self.MAXIMUM_LUM_VALUE)

        self.lums_moving_average     = np.full((feed_height, feed_width), -1, dtype=np.int32)
        self.color_distance_from_red = np.zeros((feed_height, feed_width), dtype=np.int32)
        self.lum_variance            = np.zeros((feed_height, feed_width), dtype=np.float32)

        self._temporal_buffer: deque = deque(
            [np.zeros((feed_height, feed_width), dtype=np.uint8)
             for _ in range(temporal_window)],
            maxlen=temporal_window,
        )

        self.moving_average_period = 5
        self.frame_count           = 0
        self.avg_threshold_pixels  = -1

        frame_size = feed_width * feed_height
        self.MAXIMUM_THRESHOLD_PIXELS_FOR_AVG = int(frame_size * 0.000976)
        self.MINIMUM_SHOT_DIMENSION = (
            max(int(min_shot_dimension), 1)
            if min_shot_dimension is not None
            else max(int(frame_size * 0.000025), 1)
        )
        self.filters_initialized = False

        self.last_candidate_count = 0
        self.last_cluster_count   = 0
        self.last_shot_count      = 0
        self.last_max_lum         = 0
        self.last_max_increase    = 0
        self.last_dynamic_ratio   = 0.0
        self.last_excessive_count = 0

    def set_roi(self, mask: Optional[np.ndarray]):
        self.roi_mask = mask

    def reset(self):
        self.lums_moving_average[:]     = -1
        self.color_distance_from_red[:] = 0
        self.lum_variance[:]            = 0
        for buf in self._temporal_buffer:
            buf[:] = 0
        self.avg_threshold_pixels = -1
        self.filters_initialized  = False
        self.frame_count          = 0
        self.deduplicator.reset()

    def _compute_luminance(self, s, v):
        legacy    = (255 - s) * v
        saturated = (s + 1)   * v
        if self.luminance_mode == "legacy":    return legacy
        if self.luminance_mode == "saturated": return saturated
        if self.luminance_mode == "value":     return v * 255
        if self.luminance_mode == "adaptive":  return np.maximum(legacy, saturated)
        return (legacy.astype(np.float32) * 0.6
                + saturated.astype(np.float32) * 0.4).astype(np.int32)

    def _update_period(self, fps: int = 30):
        if self.frame_count % 5 == 0:
            self.moving_average_period = max(int(fps / 5.0), 5)

    def process_frame(self, frame_bgr: np.ndarray, fps: int = 30) -> List[Dict]:
        self.frame_count += 1
        self._update_period(fps)

        if frame_bgr is None or frame_bgr.size == 0:
            self._zero_diagnostics()
            return []

        if frame_bgr.ndim == 2 or (frame_bgr.ndim == 3 and frame_bgr.shape[2] == 1):
            frame_bgr = cv2.cvtColor(frame_bgr, cv2.COLOR_GRAY2BGR)

        frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV).astype(np.int32)
        H = frame_hsv[:, :, 0]
        S = frame_hsv[:, :, 1]
        V = frame_hsv[:, :, 2]

        current_lum  = self._compute_luminance(S, V)
        h_dist_red   = np.minimum(H, np.abs(180 - H))
        h_dist_green = np.abs(60 - H)
        temp_cdr     = (h_dist_red - h_dist_green) * S * V

        uninit = self.lums_moving_average == -1
        if uninit.any():
            self.lums_moving_average[uninit]     = current_lum[uninit]
            self.color_distance_from_red[uninit] = temp_cdr[uninit]
            self._zero_diagnostics()
            return []

        if not self.filters_initialized:
            if self.frame_count > 5:
                self.filters_initialized = True
            self._update_averages(current_lum, temp_cdr)
            self._zero_diagnostics()
            return []

        increase = current_lum - self.lums_moving_average

        if self.use_variance_threshold:
            deviation         = increase.astype(np.float32)
            self.lum_variance = (self.variance_alpha * deviation ** 2
                                 + (1 - self.variance_alpha) * self.lum_variance)
            std_dev            = np.sqrt(self.lum_variance).astype(np.int32)
            variance_threshold = (self.variance_k * std_dev).astype(np.int32)
        else:
            variance_threshold = np.zeros_like(increase)

        base_threshold = (self.MAXIMUM_LUM_VALUE - self.lums_moving_average) >> 2
        avg_tp  = self.avg_threshold_pixels if self.avg_threshold_pixels != -1 else 0
        dyn_ratio = min(avg_tp / max(self.MAXIMUM_THRESHOLD_PIXELS_FOR_AVG, 1),
                        self.max_dynamic_ratio)
        self.last_dynamic_ratio = float(dyn_ratio)

        if self.use_dynamic_threshold:
            dynamic_threshold = base_threshold + (
                (self.MAXIMUM_LUM_VALUE - base_threshold) * dyn_ratio
            ).astype(np.int32)
        else:
            dynamic_threshold = base_threshold

        effective_threshold = np.maximum(dynamic_threshold, variance_threshold)

        excessive_mask = (
            self.lums_moving_average > self.EXCESSIVE_BRIGHTNESS_THRESHOLD
            if self.use_excessive_mask
            else np.zeros((self.feed_height, self.feed_width), dtype=bool)
        )
        self.last_excessive_count = int(excessive_mask.sum())

        roi_mask = np.ones((self.feed_height, self.feed_width), dtype=bool)
        if self.roi_mask is not None:
            roi_mask = self.roi_mask > 0

        shot_mask = (
            (increase >= self.MINIMUM_BRIGHTNESS_INCREASE)
            & (increase >= effective_threshold)
            & ~excessive_mask
            & roi_mask
        )

        current_frame_mask = shot_mask.astype(np.uint8)
        if self.use_temporal_filter and self.temporal_min_frames > 1:
            temporal_sum  = sum(self._temporal_buffer).astype(np.uint8)
            temporal_mask = temporal_sum >= (self.temporal_min_frames - 1)
            shot_mask     = shot_mask & temporal_mask
        self._temporal_buffer.append(current_frame_mask)

        ys, xs = np.where(shot_mask)
        threshold_pixels = set()
        for y, x in zip(ys, xs):
            threshold_pixels.add(Pixel(
                x, y,
                color         = int(H[y, x]),
                current_lum   = int(current_lum[y, x]),
                lum_average   = int(self.lums_moving_average[y, x]),
                color_average = int(self.color_distance_from_red[y, x]),
            ))

        dyn_thresholded = int(
            np.sum((increase < dynamic_threshold) & (increase > base_threshold)))
        total_tp = min(
            len(threshold_pixels) + dyn_thresholded,
            self.MAXIMUM_THRESHOLD_PIXELS_FOR_AVG,
        )
        if self.avg_threshold_pixels == -1:
            self.avg_threshold_pixels = total_tp
        else:
            p = self.moving_average_period
            self.avg_threshold_pixels = int(
                ((p - 1) * self.avg_threshold_pixels + total_tp) / p)

        self._update_averages(current_lum, temp_cdr)

        self.last_max_lum         = int(current_lum.max()) if current_lum.size else 0
        self.last_max_increase    = int(increase.max())    if increase.size    else 0
        self.last_candidate_count = len(threshold_pixels)
        self.last_cluster_count   = 0
        self.last_shot_count      = 0

        if len(threshold_pixels) < self.MINIMUM_SHOT_DIMENSION:
            return []

        clusters = self.pixel_cluster_manager.cluster_pixels(
            threshold_pixels, self.MINIMUM_SHOT_DIMENSION)
        self.last_cluster_count = len(clusters)

        shots: List[Dict] = []
        for cluster in clusters:
            color = cluster.get_color(frame_hsv, self.color_distance_from_red)
            if color is None:
                continue
            x, y = cluster.center_pixel_x, cluster.center_pixel_y
            if self.deduplicator.is_duplicate(x, y):
                continue
            inc_at_center = (
                float(increase[int(y), int(x)])
                if 0 <= int(y) < self.feed_height and 0 <= int(x) < self.feed_width
                else 0.0
            )
            inc_confidence = min(inc_at_center / (self.MAXIMUM_LUM_VALUE * 0.5), 1.0)
            confidence = round(0.4 * cluster.color_confidence + 0.6 * inc_confidence, 3)
            shots.append({"x": x, "y": y, "color": color, "confidence": confidence})

        self.last_shot_count = len(shots)
        return shots

    def _update_averages(self, current_lum, temp_cdr):
        p = self.moving_average_period
        self.lums_moving_average = (
            (self.lums_moving_average * (p - 1) + current_lum) // p)
        self.color_distance_from_red = (
            (self.color_distance_from_red * (p - 1) + temp_cdr) // p)

    def _zero_diagnostics(self):
        self.last_candidate_count = 0
        self.last_cluster_count   = 0
        self.last_shot_count      = 0
        self.last_max_lum         = 0
        self.last_max_increase    = 0
        self.last_dynamic_ratio   = 0.0
        self.last_excessive_count = 0


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — FastAPI application
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI()

CALIBRATION_TIMEOUT_SECONDS      = 8.0
_SHOT_LUMINANCE_MODE              = "combined"
SHOT_BRIGHTNESS_INCREASE_RATIO    = 0.10
_SHOT_EXCESSIVE_BRIGHTNESS_RATIO  = 0.96
_SHOT_MIN_DIMENSION               = 8
_SHOT_DYNAMIC_RATIO_CAP           = 0.25
_SHOT_USE_DYNAMIC_THRESHOLD       = True
_SHOT_USE_EXCESSIVE_MASK          = True
_SHOT_USE_VARIANCE_THRESHOLD      = True
_SHOT_VARIANCE_ALPHA              = 0.05
_SHOT_VARIANCE_K                  = 2.5
_SHOT_USE_TEMPORAL_FILTER         = True
_SHOT_TEMPORAL_WINDOW             = 3
_SHOT_TEMPORAL_MIN_FRAMES         = 1
DEBUG_FRAME_STATS                 = True
BLACK_FRAME_STREAK_LIMIT          = 15
DEBUG_PREVIEW_ENABLED             = False
DEBUG_PREVIEW_SECONDS             = 4.0
DEBUG_PREVIEW_SQUARE_RATIO        = 0.35
DEBUG_PREVIEW_WINDOW              = "ShootOFF Debug Preview"
DEBUG_BBOX_PREVIEW_SECONDS        = 6.0


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    x1, y1, x2, y2 = [int(v) for v in bbox]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return left, top, right, bottom


def is_valid_bbox(bbox):
    left, top, right, bottom = bbox
    return right > left and bottom > top


def build_roi_mask(width, height, bbox):
    mask = np.zeros((height, width), dtype=np.uint8)
    left, top, right, bottom = bbox
    left   = max(0, min(left,   width  - 1))
    right  = max(0, min(right,  width  - 1))
    top    = max(0, min(top,    height - 1))
    bottom = max(0, min(bottom, height - 1))
    if right <= left or bottom <= top:
        return mask
    mask[top:bottom + 1, left:right + 1] = 255
    return mask


def draw_center_square(frame, ratio, color=(255, 255, 255), thickness=2):
    height, width = frame.shape[:2]
    size  = max(1, int(min(width, height) * ratio))
    half  = size // 2
    cx, cy = width // 2, height // 2
    x1 = max(cx - half, 0);   y1 = max(cy - half, 0)
    x2 = min(cx + half, width - 1); y2 = min(cy + half, height - 1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)


def draw_bbox(frame, bbox, color=(0, 255, 255), thickness=2):
    left, top, right, bottom = bbox
    cv2.rectangle(frame, (left, top), (right, bottom), color, thickness)


def parse_bool_param(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):  return True
    if text in ("0", "false", "no", "n", "off"): return False
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


# ── Main service class ────────────────────────────────────────────────────────

class ManualBBoxEditor:
    """Mouse-driven bbox editor for the OpenCV calibration preview."""

    _HANDLE_RADIUS = 10
    _MIN_SIZE = 10

    def __init__(self, bbox, frame_shape):
        height, width = frame_shape[:2]
        self.frame_width = max(int(width), 1)
        self.frame_height = max(int(height), 1)
        self.bbox = self._clamp_bbox(normalize_bbox(bbox))
        self._drag_mode = None
        self._drag_start = None
        self._drag_bbox = None

    def on_mouse(self, event, x, y, flags, userdata):
        del flags, userdata

        if event == cv2.EVENT_LBUTTONDOWN:
            handle = self._hit_test_handle(x, y)
            if handle is not None:
                self._drag_mode = handle
            elif self._point_in_bbox(x, y):
                self._drag_mode = "move"
            else:
                self._drag_mode = "create"
            self._drag_start = (x, y)
            self._drag_bbox = self.bbox
            if self._drag_mode == "create":
                self.bbox = self._clamp_bbox((x, y, x, y))
            return

        if self._drag_mode is None:
            return

        if event == cv2.EVENT_MOUSEMOVE:
            self._apply_drag(x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self._apply_drag(x, y)
            self._drag_mode = None
            self._drag_start = None
            self._drag_bbox = None

    def render(self, frame, corner_points=None):
        preview = frame
        left, top, right, bottom = self.bbox

        overlay = preview.copy()
        cv2.rectangle(overlay, (left, top), (right, bottom), (0, 255, 255), -1)
        cv2.addWeighted(overlay, 0.14, preview, 0.86, 0, preview)
        draw_center_square(preview, DEBUG_PREVIEW_SQUARE_RATIO, color=(255, 255, 255), thickness=1)
        draw_bbox(preview, self.bbox, color=(0, 255, 255), thickness=3)

        if corner_points is not None:
            for pt in corner_points:
                cv2.circle(preview, (int(pt[0]), int(pt[1])), 5, (0, 255, 255), -1)

        for handle_x, handle_y in self._handle_points():
            cv2.circle(preview, (handle_x, handle_y), 7, (0, 0, 0), -1)
            cv2.circle(preview, (handle_x, handle_y), 4, (255, 255, 255), -1)

        self._draw_text(preview, "Drag inside to move. Drag corners to resize.", 28)
        self._draw_text(preview, "Press Enter to accept the bbox.", 54)
        self._draw_text(
            preview,
            f"BBox: {left}, {top} -> {right}, {bottom}",
            80,
        )
        return preview

    def _apply_drag(self, x, y):
        if self._drag_mode is None or self._drag_start is None or self._drag_bbox is None:
            return

        start_left, start_top, start_right, start_bottom = self._drag_bbox
        if self._drag_mode == "move":
            dx = x - self._drag_start[0]
            dy = y - self._drag_start[1]
            self.bbox = self._shift_bbox(self._drag_bbox, dx, dy)
        elif self._drag_mode == "tl":
            self.bbox = self._clamp_bbox((x, y, start_right, start_bottom))
        elif self._drag_mode == "tr":
            self.bbox = self._clamp_bbox((start_left, y, x, start_bottom))
        elif self._drag_mode == "br":
            self.bbox = self._clamp_bbox((start_left, start_top, x, y))
        elif self._drag_mode == "bl":
            self.bbox = self._clamp_bbox((x, start_top, start_right, y))
        elif self._drag_mode == "create":
            self.bbox = self._clamp_bbox((self._drag_start[0], self._drag_start[1], x, y))

    def _shift_bbox(self, bbox, dx, dy):
        left, top, right, bottom = bbox

        left += dx
        right += dx
        top += dy
        bottom += dy

        if left < 0:
            right -= left
            left = 0
        if top < 0:
            bottom -= top
            top = 0
        if right > self.frame_width - 1:
            left -= right - (self.frame_width - 1)
            right = self.frame_width - 1
        if bottom > self.frame_height - 1:
            top -= bottom - (self.frame_height - 1)
            bottom = self.frame_height - 1

        return self._clamp_bbox((left, top, right, bottom))

    def _clamp_bbox(self, bbox):
        left, top, right, bottom = normalize_bbox(bbox)

        left = self._clamp(left, 0, self.frame_width - 1)
        right = self._clamp(right, 0, self.frame_width - 1)
        top = self._clamp(top, 0, self.frame_height - 1)
        bottom = self._clamp(bottom, 0, self.frame_height - 1)

        if right - left < self._MIN_SIZE:
            right = min(self.frame_width - 1, left + self._MIN_SIZE)
            if right - left < self._MIN_SIZE:
                left = max(0, right - self._MIN_SIZE)

        if bottom - top < self._MIN_SIZE:
            bottom = min(self.frame_height - 1, top + self._MIN_SIZE)
            if bottom - top < self._MIN_SIZE:
                top = max(0, bottom - self._MIN_SIZE)

        if right <= left:
            right = min(self.frame_width - 1, left + self._MIN_SIZE)
        if bottom <= top:
            bottom = min(self.frame_height - 1, top + self._MIN_SIZE)

        return (
            int(self._clamp(left, 0, self.frame_width - 1)),
            int(self._clamp(top, 0, self.frame_height - 1)),
            int(self._clamp(right, 0, self.frame_width - 1)),
            int(self._clamp(bottom, 0, self.frame_height - 1)),
        )

    def _point_in_bbox(self, x, y):
        left, top, right, bottom = self.bbox
        return left <= x <= right and top <= y <= bottom

    def _hit_test_handle(self, x, y):
        for name, handle_x, handle_y in self._handle_points(named=True):
            if abs(x - handle_x) <= self._HANDLE_RADIUS and abs(y - handle_y) <= self._HANDLE_RADIUS:
                return name
        return None

    def _handle_points(self, named=False):
        left, top, right, bottom = self.bbox
        handles = (
            ("tl", left, top),
            ("tr", right, top),
            ("br", right, bottom),
            ("bl", left, bottom),
        )
        if named:
            return handles
        return [(x, y) for _, x, y in handles]

    @staticmethod
    def _draw_text(frame, text, y):
        cv2.putText(
            frame,
            text,
            (16, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            text,
            (16, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def _clamp(value, minimum, maximum):
        return max(minimum, min(maximum, int(value)))


class ShootOffAPI:
    def __init__(self, config=None, prefs=None, calibrator=None,
                 detector_factory=None, argv=None,
                 camera_calibration_file: Optional[str] = None):
        self.config = (config if config is not None
                       else Configurator(argv=[] if argv is None else argv))
        self.prefs  = prefs if prefs is not None else self.config.get_preferences()
        self.calibrator = (calibrator if calibrator is not None
                           else ProjectorCalibrator(
                               calibration_file=camera_calibration_file))
        self.detector_factory = (detector_factory if detector_factory is not None
                                 else self._build_detector)
        self.active_bbox            = None
        self.active_homography: Optional[np.ndarray] = None   # ← Zhang H
        self.calibration_confidence = 0.0

    def reset_calibration(self):
        self.active_bbox            = None
        self.active_homography      = None
        self.calibration_confidence = 0.0
        if hasattr(self.calibrator, "reset"):
            self.calibrator.reset()

    # ── Preference helpers ────────────────────────────────────────────────────

    def _pref_bool(self, key, default):
        value = self.prefs.get(key, default)
        if isinstance(value, bool): return value
        if value is None:           return default
        text = str(value).strip().lower()
        if text in ("true",  "1", "yes", "y", "on"):  return True
        if text in ("false", "0", "no",  "n", "off"): return False
        return default

    def _pref_int(self, key, default):
        try:   return int(self.prefs.get(key, default))
        except (TypeError, ValueError): return default

    def _pref_float(self, key, default):
        try:   return float(self.prefs.get(key, default))
        except (TypeError, ValueError): return default

    def _pref_str(self, key, default):
        value = self.prefs.get(key, default)
        text  = str(value).strip() if value is not None else ""
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
        return (raw_x >= bbox[0] and raw_x <= bbox[2]
                and raw_y >= bbox[1] and raw_y <= bbox[3])

    def _build_detector(self, width, height):
        brightness_ratio = self._intensity_to_ratio(self.prefs.get(LASER_INTENSITY))
        return JavaShotDetector(
            width, height,
            luminance_mode             = self._pref_str(SHOT_LUMINANCE_MODE,        _SHOT_LUMINANCE_MODE),
            brightness_increase_ratio  = brightness_ratio,
            excessive_brightness_ratio = self._pref_float(SHOT_EXCESSIVE_BRIGHTNESS_RATIO, _SHOT_EXCESSIVE_BRIGHTNESS_RATIO),
            min_shot_dimension         = self._pref_int(SHOT_MIN_DIMENSION,          _SHOT_MIN_DIMENSION),
            max_dynamic_ratio          = self._pref_float(SHOT_DYNAMIC_RATIO_CAP,    _SHOT_DYNAMIC_RATIO_CAP),
            use_dynamic_threshold      = self._pref_bool(SHOT_USE_DYNAMIC_THRESHOLD, _SHOT_USE_DYNAMIC_THRESHOLD),
            use_variance_threshold     = self._pref_bool(SHOT_USE_VARIANCE_THRESHOLD,_SHOT_USE_VARIANCE_THRESHOLD),
            variance_alpha             = self._pref_float(SHOT_VARIANCE_ALPHA,        _SHOT_VARIANCE_ALPHA),
            variance_k                 = self._pref_float(SHOT_VARIANCE_K,            _SHOT_VARIANCE_K),
            use_temporal_filter        = self._pref_bool(SHOT_USE_TEMPORAL_FILTER,   _SHOT_USE_TEMPORAL_FILTER),
            temporal_window            = self._pref_int(SHOT_TEMPORAL_WINDOW,        _SHOT_TEMPORAL_WINDOW),
            temporal_min_frames        = self._pref_int(SHOT_TEMPORAL_MIN_FRAMES,    _SHOT_TEMPORAL_MIN_FRAMES),
            use_excessive_mask         = self._pref_bool(SHOT_USE_EXCESSIVE_MASK,    _SHOT_USE_EXCESSIVE_MASK),
        )

    def _build_shot_candidate(self, shot, bbox, ignore_color):
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
            "raw_x": raw_x, "raw_y": raw_y,
            "color": shot_color,
            "confidence": round(confidence, 3),
        }

    def _map_shot_to_arena(
        self,
        raw_x: float, raw_y: float,
        bbox,
        arena_w: int, arena_h: int,
        homography: Optional[np.ndarray] = None,
    ) -> Tuple[float, float]:
        """
        Map a camera-pixel shot coordinate to arena space.

        Priority:
          1. Zhang homography (full perspective warp) — most accurate.
          2. Linear bbox scaling (legacy affine fallback).
        """
        # ── 1. Zhang perspective warp ─────────────────────────────────────────
        if homography is not None and homography.shape == (3, 3):
            try:
                pt      = np.array([[[raw_x, raw_y]]], dtype=np.float32)
                warped  = cv2.perspectiveTransform(pt, homography)
                norm_x  = float(warped[0, 0, 0])
                norm_y  = float(warped[0, 0, 1])
                if np.isfinite(norm_x) and np.isfinite(norm_y):
                    return (
                        float(np.clip(norm_x * arena_w, 0.0, float(arena_w))),
                        float(np.clip(norm_y * arena_h, 0.0, float(arena_h))),
                    )
            except cv2.error as exc:
                print(f"SHOT_DEBUG warning=homography_warp_failed err={exc}")

        # ── 2. Legacy linear bbox fallback ────────────────────────────────────
        bbox_width  = float(bbox[2] - bbox[0])
        bbox_height = float(bbox[3] - bbox[1])
        if bbox_width < 10.0 or bbox_height < 10.0:
            print(f"SHOT_DEBUG warning=invalid_bbox bbox={bbox} "
                  f"width={bbox_width:.2f} height={bbox_height:.2f}")
            return 0.0, 0.0
        x_scale = float(arena_w) / bbox_width
        y_scale = float(arena_h) / bbox_height
        return (
            float(np.clip((raw_x - bbox[0]) * x_scale, 0.0, float(arena_w))),
            float(np.clip((raw_y - bbox[1]) * y_scale, 0.0, float(arena_h))),
        )

    async def _send_calibration_status(
        self, websocket: WebSocket, status: str, *,
        bbox=None, mode=None, reason=None,
        confidence=None, elapsed_seconds=None,
        arena_w=None, arena_h=None,
        has_homography=False, marker_count=0, reproj_error=0.0,
    ):
        payload = {"status": status}
        if bbox             is not None: payload["bbox"]            = list(bbox)
        if mode             is not None: payload["mode"]            = mode
        if reason           is not None: payload["reason"]          = reason
        if confidence       is not None: payload["confidence"]      = round(float(confidence), 3)
        if elapsed_seconds  is not None: payload["elapsed_seconds"] = round(float(elapsed_seconds), 2)
        if arena_w          is not None: payload["arena_w"]         = arena_w
        if arena_h          is not None: payload["arena_h"]         = arena_h
        payload["has_homography"] = has_homography
        payload["marker_count"]   = marker_count
        if reproj_error:
            payload["reproj_error_px"] = round(float(reproj_error), 2)
        await websocket.send_json(payload)

    async def run_session(
        self,
        websocket: WebSocket,
        debug_preview=None,
        force_calibration=False,
        bbox_preview=None,
    ):
        manual_adjust_seed_bbox = (
            self.active_bbox
            if self.active_bbox is not None and is_valid_bbox(self.active_bbox)
            else None
        )
        if force_calibration:
            self.reset_calibration()

        cap = open_capture(self.prefs[VIDCAM])
        if not cap.isOpened():
            await websocket.send_json({"error": "Webcam not found"})
            cap.release()
            return

        capture_fps = get_capture_fps(cap)

        # Restore cached calibration
        active_bbox        = (self.active_bbox
                              if self.active_bbox is not None
                              and is_valid_bbox(self.active_bbox) else None)
        active_homography  = self.active_homography
        calibration_locked = active_bbox is not None
        calibration_start  = time.monotonic()
        if force_calibration:
            active_bbox = None
            active_homography = None
            calibration_locked = False

        def _result_marker_count(calibration_result):
            return int(getattr(calibration_result, "marker_count", 0) or 0)

        def _result_reproj_error(calibration_result):
            return float(getattr(calibration_result, "reproj_error", 0.0) or 0.0)

        def _result_has_homography(calibration_result):
            value = getattr(calibration_result, "has_homography", None)
            if value is not None:
                return bool(value)
            homography = _result_homography(calibration_result)
            if homography is None:
                return False
            shape = getattr(homography, "shape", None)
            return shape is None or shape == (3, 3)

        def _result_homography(calibration_result):
            return getattr(calibration_result, "homography", None)

        def _result_corners_px(calibration_result):
            return getattr(calibration_result, "corners_px", None)

        try:
            arena_w = int(websocket.query_params.get("arena_w"))
            arena_h = int(websocket.query_params.get("arena_h"))
            if arena_w < 1 or arena_h < 1:
                raise ValueError
        except (TypeError, ValueError):
            await websocket.send_json({"error": "Missing or invalid arena_w/arena_h"})
            cap.release()
            return

        last_shot_time       = 0.0
        min_shot_interval    = 0.15
        detector             = None
        detector_frame_shape = None
        detector_intensity   = None
        detector_roi_bbox    = None
        ignore_color         = str(self.prefs.get(IGNORE_LASER_COLOR, "none")).lower()
        last_debug_log       = 0.0
        debug_interval       = 1.0
        black_frame_streak   = 0
        debug_preview_until  = None
        debug_window_open    = False
        debug_preview_enabled = (DEBUG_PREVIEW_ENABLED
                                 if debug_preview is None else debug_preview)
        bbox_preview_enabled  = False if bbox_preview is None else bbox_preview
        preview_enabled       = debug_preview_enabled or bbox_preview_enabled
        manual_adjust_active  = False
        manual_adjust_editor  = None

        if preview_enabled:
            debug_preview_until = time.monotonic() + DEBUG_PREVIEW_SECONDS

        if calibration_locked:
            await self._send_calibration_status(
                websocket, "calibrated",
                bbox=active_bbox, mode="cached",
                confidence=self.calibration_confidence,
                elapsed_seconds=0.0,
                arena_w=arena_w, arena_h=arena_h,
                has_homography=active_homography is not None,
                marker_count=0,
                reproj_error=0.0,
            )

        last_frame_shape = None

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    await websocket.send_json({"error": "Camera frame read failed"})
                    break

                frame_shape = frame.shape[:2]
                if last_frame_shape is None:
                    last_frame_shape = frame_shape
                elif frame_shape != last_frame_shape:
                    print(f"SHOT_DEBUG warning=frame_shape_changed "
                          f"from={last_frame_shape} to={frame_shape}")
                    self.reset_calibration()
                    active_bbox        = None
                    active_homography  = None
                    calibration_locked = False
                    manual_adjust_seed_bbox = None
                    manual_adjust_active = False
                    manual_adjust_editor = None
                    calibration_start  = time.monotonic()
                    last_frame_shape   = frame_shape
                    if debug_window_open:
                        try:
                            cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                        except Exception:
                            pass
                        debug_window_open = False

                frame_max = int(np.max(frame)) if frame is not None and frame.size else 0
                if frame_max == 0:
                    black_frame_streak += 1
                    if black_frame_streak >= BLACK_FRAME_STREAK_LIMIT:
                        print("SHOT_DEBUG warning=black_frames reopening_camera")
                        cap.release()
                        cap = open_capture(self.prefs[VIDCAM])
                        if not cap.isOpened():
                            await websocket.send_json({"error": "Webcam not found"})
                            break
                        capture_fps        = get_capture_fps(cap)
                        black_frame_streak = 0
                    await asyncio.sleep(self.prefs[DETECTION_RATE] / 1000.0)
                    continue
                else:
                    black_frame_streak = 0

                if not calibration_locked and manual_adjust_editor is None:
                    seed_bbox = (
                        manual_adjust_seed_bbox
                        if manual_adjust_seed_bbox is not None
                        and is_valid_bbox(manual_adjust_seed_bbox)
                        else (0, 0, frame.shape[1] - 1, frame.shape[0] - 1)
                    )
                    manual_adjust_editor = ManualBBoxEditor(
                        normalize_bbox(seed_bbox),
                        frame.shape[:2],
                    )
                    manual_adjust_active = True
                    elapsed_seconds = time.monotonic() - calibration_start
                    await self._send_calibration_status(
                        websocket, "manual_adjusting",
                        bbox=manual_adjust_editor.bbox,
                        mode="manual",
                        reason=(
                            "Drag the bbox in the preview window, then press "
                            "Enter to accept."
                        ),
                        confidence=1.0,
                        elapsed_seconds=elapsed_seconds,
                        arena_w=arena_w, arena_h=arena_h,
                        has_homography=False,
                        marker_count=0,
                        reproj_error=0.0,
                    )

                # ── Debug preview window ───────────────────────────────────
                if (
                    preview_enabled
                    and debug_preview_until is not None
                    and not manual_adjust_active
                ):
                    now_p = time.monotonic()
                    if now_p <= debug_preview_until:
                        preview = frame.copy()
                        preview_bbox = (
                            active_bbox
                            if active_bbox is not None and is_valid_bbox(active_bbox)
                            else None
                        )
                        if preview_bbox is not None and is_valid_bbox(preview_bbox):
                            draw_bbox(preview, preview_bbox)
                        try:
                            if not debug_window_open:
                                cv2.namedWindow(DEBUG_PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
                                cv2.resizeWindow(
                                    DEBUG_PREVIEW_WINDOW,
                                    int(frame.shape[1]),
                                    int(frame.shape[0]),
                                )
                                debug_window_open = True
                            cv2.imshow(DEBUG_PREVIEW_WINDOW, preview)
                            cv2.waitKey(1)
                        except Exception:
                            preview_enabled = False
                            if debug_window_open:
                                cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                                debug_window_open   = False
                                debug_preview_until = None
                    else:
                        if debug_window_open:
                            cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                            debug_window_open = False
                        debug_preview_until = None

                if manual_adjust_active and manual_adjust_editor is not None:
                    try:
                        preview = manual_adjust_editor.render(frame.copy())
                        if not debug_window_open:
                            cv2.namedWindow(DEBUG_PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
                            cv2.resizeWindow(
                                DEBUG_PREVIEW_WINDOW,
                                int(frame.shape[1]),
                                int(frame.shape[0]),
                            )
                            debug_window_open = True
                        cv2.setMouseCallback(
                            DEBUG_PREVIEW_WINDOW,
                            manual_adjust_editor.on_mouse,
                        )
                        cv2.imshow(DEBUG_PREVIEW_WINDOW, preview)
                        key = cv2.waitKey(1) & 0xFF
                    except Exception as exc:
                        print(f"CALIB warning=manual_bbox_preview_failed err={exc}")
                        await websocket.send_json({
                            "error": f"Manual calibration preview failed: {exc}",
                        })
                        return

                    if key in (13, 10):
                        accepted_bbox = manual_adjust_editor.bbox
                        calibration_locked = True
                        active_bbox = accepted_bbox
                        active_homography = None
                        self.active_bbox = accepted_bbox
                        self.active_homography = active_homography
                        self.calibration_confidence = 1.0
                        manual_adjust_active = False
                        manual_adjust_editor = None
                        elapsed_seconds = time.monotonic() - calibration_start
                        await self._send_calibration_status(
                            websocket, "calibrated",
                            bbox=accepted_bbox, mode="manual",
                            reason="manual bbox accepted",
                            confidence=1.0,
                            elapsed_seconds=elapsed_seconds,
                            arena_w=arena_w, arena_h=arena_h,
                            has_homography=False,
                            marker_count=0,
                            reproj_error=0.0,
                        )
                        debug_preview_until = None
                        try:
                            if debug_window_open:
                                cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                        except Exception:
                            pass
                        debug_window_open = False
                        continue

                    await asyncio.sleep(0.03)
                    continue

                if not calibration_locked:
                    await asyncio.sleep(self.prefs[DETECTION_RATE] / 1000.0)
                    continue

                frame_height, frame_width = frame.shape[:2]
                laser_intensity = self.prefs.get(LASER_INTENSITY)

                if (detector is None
                        or detector_frame_shape != (frame_width, frame_height)
                        or detector_intensity != laser_intensity):
                    detector             = self.detector_factory(frame_width, frame_height)
                    detector_frame_shape = (frame_width, frame_height)
                    detector_intensity   = laser_intensity
                    detector_roi_bbox    = None

                # ── 1. Calibration phase ───────────────────────────────────
                if False and not calibration_locked:
                    self.calibrator.calibrate_projector(frame)
                    result          = self.calibrator.get_result()
                    elapsed_seconds = time.monotonic() - calibration_start

                    if result.valid:
                        normalized_bbox = normalize_bbox(result.as_bbox())
                        if is_valid_bbox(normalized_bbox):
                            mode_str = ("zhang_4pt" if _result_marker_count(result) == 4
                                        else "zhang_2pt_affine")
                            if preview_enabled:
                                try:
                                    manual_adjust_editor = ManualBBoxEditor(
                                        normalized_bbox, frame.shape[:2])
                                    if not debug_window_open:
                                        cv2.namedWindow(
                                            DEBUG_PREVIEW_WINDOW,
                                            cv2.WINDOW_NORMAL,
                                        )
                                        debug_window_open = True
                                    cv2.resizeWindow(
                                        DEBUG_PREVIEW_WINDOW,
                                        int(frame.shape[1]),
                                        int(frame.shape[0]),
                                    )
                                    cv2.setMouseCallback(
                                        DEBUG_PREVIEW_WINDOW,
                                        manual_adjust_editor.on_mouse,
                                    )
                                    manual_adjust_active = True
                                    manual_adjust_result = result
                                    await self._send_calibration_status(
                                        websocket, "manual_adjusting",
                                        bbox=normalized_bbox, mode=mode_str,
                                        reason=(
                                            "Drag the bbox in the preview "
                                            "window, then press Enter to accept."
                                        ),
                                        confidence=result.confidence,
                                        elapsed_seconds=elapsed_seconds,
                                        arena_w=arena_w, arena_h=arena_h,
                                        has_homography=_result_has_homography(result),
                                        marker_count=_result_marker_count(result),
                                        reproj_error=_result_reproj_error(result),
                                    )
                                    continue
                                except Exception as exc:
                                    print(
                                        "CALIB warning=manual_bbox_preview_setup_failed "
                                        f"err={exc}"
                                    )
                                    manual_adjust_editor = None
                                    manual_adjust_active = False
                                    manual_adjust_result = None
                                    if debug_window_open:
                                        try:
                                            cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)
                                        except Exception:
                                            pass
                                        debug_window_open = False

                            calibration_locked          = True
                            active_bbox                 = normalized_bbox
                            active_homography           = _result_homography(result)   # ← Zhang H
                            self.active_bbox            = normalized_bbox
                            self.active_homography      = _result_homography(result)
                            self.calibration_confidence = float(result.confidence)

                            await self._send_calibration_status(
                                websocket, "calibrated",
                                bbox=normalized_bbox, mode=mode_str,
                                confidence=result.confidence,
                                elapsed_seconds=elapsed_seconds,
                                arena_w=arena_w, arena_h=arena_h,
                                has_homography=_result_has_homography(result),
                                marker_count=_result_marker_count(result),
                                reproj_error=_result_reproj_error(result),
                            )
                            if preview_enabled:
                                debug_preview_until = (
                                    time.monotonic() + DEBUG_BBOX_PREVIEW_SECONDS)
                        else:
                            await self._send_calibration_status(
                                websocket, "calibrating",
                                elapsed_seconds=elapsed_seconds)
                            await asyncio.sleep(0.1)
                            continue
                    else:
                        if elapsed_seconds >= CALIBRATION_TIMEOUT_SECONDS:
                            await self._send_calibration_status(
                                websocket, "calibration_failed",
                                reason="timeout", elapsed_seconds=elapsed_seconds)
                            return
                        await self._send_calibration_status(
                            websocket, "calibrating",
                            elapsed_seconds=elapsed_seconds)
                        await asyncio.sleep(0.1)
                        continue

                # ── 2. Refresh homography on each frame (EMA) ──────────────
                result = self.calibrator.get_result()
                if _result_has_homography(result):
                    active_homography      = _result_homography(result)
                    self.active_homography = _result_homography(result)

                # ── 3. Shot detection phase ────────────────────────────────
                if active_bbox is None:
                    result = self.calibrator.get_result()
                    if result.valid:
                        normalized_bbox = normalize_bbox(result.as_bbox())
                        if is_valid_bbox(normalized_bbox):
                            active_bbox            = normalized_bbox
                            self.active_bbox       = normalized_bbox
                            active_homography      = _result_homography(result)
                            self.active_homography = _result_homography(result)

                if active_bbox is None or not is_valid_bbox(active_bbox):
                    await asyncio.sleep(self.prefs[DETECTION_RATE] / 1000.0)
                    continue

                bbox = active_bbox
                frame_height, frame_width = frame.shape[:2]

                if DEBUG_FRAME_STATS and frame is not None and frame.size:
                    avg_pixel  = float(np.mean(frame))
                    max_pixel  = int(np.max(frame))
                    shape_info = frame.shape
                    dtype_info = str(frame.dtype)
                else:
                    avg_pixel = 0.0; max_pixel = 0
                    shape_info = dtype_info = None

                if detector is not None and bbox is not None and is_valid_bbox(bbox):
                    if detector_roi_bbox != bbox:
                        detector.set_roi(build_roi_mask(frame_width, frame_height, bbox))
                        detector_roi_bbox = bbox

                shots = detector.process_frame(
                    frame, fps=max(int(round(capture_fps)), 1))

                shot_candidates = []
                for shot in shots:
                    candidate = self._build_shot_candidate(shot, bbox, ignore_color)
                    if candidate is not None:
                        shot_candidates.append(candidate)

                now_debug = time.monotonic()
                if now_debug - last_debug_log >= debug_interval:
                    last_debug_log = now_debug
                    result = self.calibrator.get_result()
                    print(
                        "SHOT_DEBUG candidates={} clusters={} shots={} max_lum={} "
                        "max_inc={} min_dim={} dyn_ratio={} excessive={} "
                        "frame_shape={} dtype={} avg_px={:.2f} max_px={} bbox={} "
                        "homography={} markers={} reproj={:.1f}px".format(
                            getattr(detector, "last_candidate_count", 0),
                            getattr(detector, "last_cluster_count",   0),
                            getattr(detector, "last_shot_count",      0),
                            getattr(detector, "last_max_lum",         0),
                            getattr(detector, "last_max_increase",    0),
                            getattr(detector, "MINIMUM_SHOT_DIMENSION", 0),
                            getattr(detector, "last_dynamic_ratio",   0.0),
                            getattr(detector, "last_excessive_count", 0),
                            shape_info, dtype_info,
                            avg_pixel, max_pixel, bbox,
                            active_homography is not None,
                            _result_marker_count(result),
                            _result_reproj_error(result),
                        )
                    )

                if not shot_candidates:
                    await asyncio.sleep(self.prefs[DETECTION_RATE] / 1000.0)
                    continue

                best_shot = max(shot_candidates, key=lambda c: c["confidence"])

                now = time.monotonic()
                if now - last_shot_time < min_shot_interval:
                    await asyncio.sleep(self.prefs[DETECTION_RATE] / 1000.0)
                    continue

                last_shot_time = now
                calibrated_x, calibrated_y = self._map_shot_to_arena(
                    best_shot["raw_x"], best_shot["raw_y"],
                    bbox, arena_w, arena_h,
                    homography=active_homography,   # ← Zhang warp
                )

                await websocket.send_json({
                    "event":        "shot",
                    "x":            calibrated_x,
                    "y":            calibrated_y,
                    "raw_x":        best_shot["raw_x"],
                    "raw_y":        best_shot["raw_y"],
                    "color":        best_shot["color"],
                    "confidence":   best_shot["confidence"],
                    "timestamp":    cv2.getTickCount(),
                    "mapped_via":   ("homography" if active_homography is not None
                                     else "bbox_linear"),
                })

                await asyncio.sleep(self.prefs[DETECTION_RATE] / 1000.0)

        except WebSocketDisconnect:
            print("Angular app disconnected")
        finally:
            cap.release()
            if debug_window_open:
                cv2.destroyWindow(DEBUG_PREVIEW_WINDOW)


# ── FastAPI wiring ─────────────────────────────────────────────────────────────

shootoff_service = ShootOffAPI()


@app.websocket("/api/ws/shots")
@app.websocket("/ws/shots")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    debug_preview     = parse_bool_param(websocket.query_params.get("debug"))
    bbox_preview      = parse_bool_param(websocket.query_params.get("bbox_preview"))
    force_calibration = parse_bool_param(websocket.query_params.get("calibrate"))
    await shootoff_service.run_session(
        websocket,
        debug_preview     = debug_preview,
        force_calibration = bool(force_calibration),
        bbox_preview      = bbox_preview,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
