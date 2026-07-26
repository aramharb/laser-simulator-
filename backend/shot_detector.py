import math
import time
from collections import deque
from typing import Iterable, List, Dict, Optional, Tuple

import cv2
import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# Pixel
# ──────────────────────────────────────────────────────────────────────────────

class Pixel:
    __slots__ = ('x', 'y', 'color', 'current_lum', 'lum_average',
                 'color_average', 'connectedness')

    def __init__(self, x, y, color=0, current_lum=0,
                 lum_average=0, color_average=0):
        self.x             = int(x)
        self.y             = int(y)
        self.color         = color
        self.current_lum   = current_lum
        self.lum_average   = lum_average
        self.color_average = color_average
        self.connectedness = 0

    def __hash__(self):   return hash((self.x, self.y))
    def __eq__(self, o):  return isinstance(o, Pixel) and self.x == o.x and self.y == o.y


# ──────────────────────────────────────────────────────────────────────────────
# PixelCluster  (enhanced colour analysis)
# ──────────────────────────────────────────────────────────────────────────────

class PixelCluster(set):
    """
    Enhancements over original:
    - Weighted colour voting (saturation × luminance weight per neighbour)
    - Separate red-hue and green-hue distance accumulation before dividing
    - Confidence score exposed for downstream filtering
    """

    CURRENT_COLOR_BIAS_MULTIPLIER = 0.8
    MAXIMUM_CONNECTEDNESS         = 8

    # Hue ranges in OpenCV (0-180)
    RED_HUE_MAX   = 15    # hues 0-15 and 165-180 are red
    RED_HUE_MIN2  = 165
    GREEN_HUE_LOW = 45
    GREEN_HUE_HIGH= 90

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.center_pixel_x: float = 0.0
        self.center_pixel_y: float = 0.0
        self.color_confidence: float = 0.0   # NEW: 0-1 certainty

    # ── colour difference (vectorised neighbour sampling) ─────────────────────
    def get_color_difference(
        self,
        working_frame_hsv: np.ndarray,
        color_distance_from_red: np.ndarray,
    ) -> int:
        rows, cols = working_frame_hsv.shape[:2]
        visited: Dict[Tuple[int,int], np.ndarray] = {}

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

        # Vectorise neighbour stats
        vals        = np.array(list(visited.values()), dtype=np.int32)  # (N,3) H,S,V
        h_arr       = vals[:, 0]
        s_arr       = vals[:, 1]
        v_arr       = vals[:, 2]

        avg_s = int(np.mean(s_arr))
        avg_v = int(np.mean(v_arr))

        # Only colourful, non-over-exposed neighbours
        useful_mask = (s_arr > avg_s) & (v_arr < avg_v)
        if not np.any(useful_mask):
            return 0

        h_u = h_arr[useful_mask]
        s_u = s_arr[useful_mask]
        v_u = v_arr[useful_mask]

        # Weight by saturation × luminance product (more colourful = more vote)
        weight = (s_u * v_u).astype(np.float32)
        weight_sum = weight.sum()
        if weight_sum == 0:
            return 0

        d_from_red   = np.minimum(h_u, np.abs(180 - h_u)) * s_u * v_u
        d_from_green = np.abs(60 - h_u) * s_u * v_u
        current_col  = (d_from_red - d_from_green).astype(np.float32)

        # Background colour bias from moving average
        keys_arr     = np.array([k for k, m in zip(visited.keys(), useful_mask) if m])

        # Build bias array aligned with useful_mask
        all_keys  = list(visited.keys())
        bias_vals = np.array(
            [color_distance_from_red[ry, rx] for (rx, ry) in all_keys],
            dtype=np.float32,
        )[useful_mask]

        col_distance_arr = current_col - self.CURRENT_COLOR_BIAS_MULTIPLIER * bias_vals
        color_distance   = float(np.sum(col_distance_arr * weight) / weight_sum)

        # Confidence: how far from zero relative to a reference scale
        ref_scale = 5000.0
        self.color_confidence = min(abs(color_distance) / ref_scale, 1.0)

        return int(color_distance)

    def get_color(
        self,
        working_frame_hsv: np.ndarray,
        color_distance_from_red: np.ndarray,
    ) -> Optional[str]:
        color_dist = self.get_color_difference(working_frame_hsv, color_distance_from_red)

        # Tighter threshold + confidence gate
        if color_dist < 1000:
            return 'RED'
        return 'GREEN'


# ──────────────────────────────────────────────────────────────────────────────
# PixelClusterManager  (enhanced flood-fill + filters)
# ──────────────────────────────────────────────────────────────────────────────

class PixelClusterManager:
    """
    Enhancements:
    - Uses a pixel lookup dict (O(1) membership) to fix the O(n²) containment check
    - Tighter but tunable filter constants
    - Returns List[PixelCluster] (was a plain list, now typed)
    """

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

    def update_frame_size(self, w: int, h: int):
        self.feed_width, self.feed_height = w, h

    # ── flood-fill ────────────────────────────────────────────────────────────
    def _preprocess(
        self,
        pixel_set: Dict[Tuple[int,int], Pixel],
        pixel_mapping: Dict[Pixel, int],
    ) -> int:
        stack            = []
        number_of_regions = -1
        too_many         = len(pixel_set) > self.EXCESSIVE_PIXEL_CUTOFF

        for key, pixel in pixel_set.items():
            if pixel in pixel_mapping:
                continue

            number_of_regions += 1
            stack.append(pixel)
            pixel_mapping[pixel] = number_of_regions

            # Early-exit: noise guard
            if too_many and number_of_regions > self.EXCESSIVE_PIXEL_REGION_COUNT:
                break

            while stack:
                pt = stack.pop()
                conn = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        nx, ny = pt.x + dx, pt.y + dy
                        if not (0 <= nx < self.feed_width and 0 <= ny < self.feed_height):
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

    # ── cluster + validate ────────────────────────────────────────────────────
    def cluster_pixels(
        self,
        clusterable_pixels: Iterable[Pixel],
        minimum_shot_dimension: int,
    ) -> List[PixelCluster]:

        # Build O(1) lookup dict
        pixel_set: Dict[Tuple[int,int], Pixel] = {
            (p.x, p.y): p for p in clusterable_pixels
        }
        if not pixel_set:
            return []

        pixel_mapping: Dict[Pixel, int] = {}
        n_regions = self._preprocess(pixel_set, pixel_mapping)

        clusters: List[PixelCluster] = []

        for region_id in range(n_regions + 1):
            cluster        = PixelCluster()
            sum_wx = sum_wy = avg_conn = 0.0
            min_x = self.feed_width;  min_y = self.feed_height
            max_x = max_y = 0

            for pixel, rid in pixel_mapping.items():
                if rid != region_id:
                    continue
                min_x = min(min_x, pixel.x); max_x = max(max_x, pixel.x)
                min_y = min(min_y, pixel.y); max_y = max(max_y, pixel.y)
                cluster.add(pixel)
                c       = pixel.connectedness
                sum_wx += pixel.x * c
                sum_wy += pixel.y * c
                avg_conn += c

            sz = len(cluster)
            if sz < minimum_shot_dimension or avg_conn == 0:
                continue

            cx           = sum_wx / avg_conn
            cy           = sum_wy / avg_conn
            avg_conn    /= sz

            scaled_min = min(
                self.MINIMUM_CONNECTEDNESS
                + (sz - minimum_shot_dimension) * self.MINIMUM_CONNECTEDNESS_FACTOR,
                self.MAXIMUM_CONNECTEDNESS_SCALE,
            )
            if avg_conn < scaled_min:
                continue

            sw     = (max_x - min_x) + 1
            sh     = (max_y - min_y) + 1
            ratio  = sw / sh

            if (sw + sh) > self.SMALL_SHOT_THRESHOLD:
                if not (self.MINIMUM_SHOT_RATIO <= ratio <= self.MAXIMUM_SHOT_RATIO):
                    continue
            else:
                if not (self.MINIMUM_SHOT_RATIO_SMALL <= ratio <= self.MAXIMUM_SHOT_RATIO_SMALL):
                    continue

            r           = (sw + sh) / 4.0
            density     = sz / (math.pi * r * r)
            if density < self.MINIMUM_DENSITY:
                continue

            cluster.center_pixel_x = cx
            cluster.center_pixel_y = cy
            clusters.append(cluster)

        return clusters


# ──────────────────────────────────────────────────────────────────────────────
# Deduplication guard
# ──────────────────────────────────────────────────────────────────────────────

class ShotDeduplicator:
    """
    Suppresses duplicate detections of the same physical shot.

    A shot is a duplicate if another shot landed within `radius_px` pixels
    AND within `cooldown_s` seconds.
    """
    def __init__(self, radius_px: float = 20.0, cooldown_s: float = 0.4):
        self.radius_px  = radius_px
        self.cooldown_s = cooldown_s
        self._history: List[Dict] = []   # {x, y, t}

    def is_duplicate(self, x: float, y: float) -> bool:
        now  = time.monotonic()
        # Expire old entries
        self._history = [
            h for h in self._history
            if now - h['t'] < self.cooldown_s
        ]
        for h in self._history:
            if math.hypot(x - h['x'], y - h['y']) < self.radius_px:
                return True
        self._history.append({'x': x, 'y': y, 't': now})
        return False

    def reset(self):
        self._history.clear()


# ──────────────────────────────────────────────────────────────────────────────
# JavaShotDetector  (enhanced)
# ──────────────────────────────────────────────────────────────────────────────

class JavaShotDetector:
    """
    Key accuracy enhancements over the original:

    1. MULTI-CHANNEL LUMINANCE  — combines (255-S)*V with a saturation-weighted
       channel so highly-saturated laser spots (low S or high S) are both caught.

    2. PER-PIXEL VARIANCE TRACKING — maintains a running variance alongside the
       moving average; pixels with high background variance get a higher personal
       threshold, drastically cutting false positives from textured / moving
       backgrounds.

    3. TEMPORAL CONSISTENCY CHECK — a candidate pixel must exceed the threshold
       in at least `temporal_min_frames` of the last N frames before it counts.
       This kills single-frame sensor noise.

    4. ROI-AWARE PROCESSING — optional mask to restrict detection to a user-
       defined region of interest (e.g. a target face only).

    5. SHOT DEDUPLICATION — spatial+temporal guard prevents the same laser dot
       from being reported multiple times as it sits still.

    6. ADAPTIVE MINIMUM BRIGHTNESS INCREASE — instead of a fixed global ratio,
       the threshold adapts per-pixel based on its own running variance so dark
       corners and bright centres of the frame are treated fairly.

    7. CONFIDENCE SCORE — every returned shot carries a 0-1 confidence value
       derived from cluster density, colour certainty, and increase magnitude.
    """

    def __init__(
        self,
        feed_width:  int,
        feed_height: int,
        # ── luminance ──────────────────────────────────────────────────────
        luminance_mode: str   = 'combined',   # legacy|saturated|value|adaptive|combined
        # ── threshold ratios ───────────────────────────────────────────────
        brightness_increase_ratio:  float = 0.10,   # lowered slightly to catch dim lasers
        excessive_brightness_ratio: float = 0.96,
        # ── dynamic threshold ──────────────────────────────────────────────
        use_dynamic_threshold: bool  = True,
        max_dynamic_ratio:     float = 0.25,
        # ── variance-adaptive threshold ────────────────────────────────────
        use_variance_threshold: bool  = True,
        variance_alpha:         float = 0.05,   # EMA factor for variance
        variance_k:             float = 2.5,    # std-devs above average to gate
        # ── temporal consistency ───────────────────────────────────────────
        use_temporal_filter:  bool = True,
        temporal_window:      int  = 3,    # frames to look back
        temporal_min_frames:  int  = 1,    # must appear in at least this many
        # ── excessive-brightness mask ──────────────────────────────────────
        use_excessive_mask:   bool  = True,
        # ── shot dimension ─────────────────────────────────────────────────
        min_shot_dimension:   Optional[int] = None,
        # ── deduplication ──────────────────────────────────────────────────
        dedup_radius_px:  float = 20.0,
        dedup_cooldown_s: float = 0.40,
        # ── ROI ────────────────────────────────────────────────────────────
        roi_mask: Optional[np.ndarray] = None,   # uint8 mask, same H×W as feed
    ):
        self.feed_width  = feed_width
        self.feed_height = feed_height

        self.pixel_cluster_manager = PixelClusterManager(feed_width, feed_height)
        self.deduplicator          = ShotDeduplicator(dedup_radius_px, dedup_cooldown_s)

        # config
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
        self.roi_mask               = roi_mask   # None → whole frame

        # absolute thresholds
        self.MAXIMUM_LUM_VALUE             = 65280
        self.EXCESSIVE_BRIGHTNESS_THRESHOLD = int(excessive_brightness_ratio * self.MAXIMUM_LUM_VALUE)
        self.MINIMUM_BRIGHTNESS_INCREASE    = int(brightness_increase_ratio   * self.MAXIMUM_LUM_VALUE)

        # per-pixel state
        self.lums_moving_average     = np.full((feed_height, feed_width), -1, dtype=np.int32)
        self.color_distance_from_red = np.zeros((feed_height, feed_width), dtype=np.int32)

        # variance state (EMA of squared deviations)
        self.lum_variance = np.zeros((feed_height, feed_width), dtype=np.float32)

        # temporal ring buffer  (bool mask per recent frame)
        self._temporal_buffer: deque = deque(
            [np.zeros((feed_height, feed_width), dtype=np.uint8)
             for _ in range(temporal_window)],
            maxlen=temporal_window,
        )

        # moving-average period
        self.moving_average_period = 5
        self.frame_count           = 0
        self.avg_threshold_pixels  = -1

        # derived dimension
        frame_size = feed_width * feed_height
        self.MAXIMUM_THRESHOLD_PIXELS_FOR_AVG = int(frame_size * 0.000976)
        self.MINIMUM_SHOT_DIMENSION = (
            max(int(min_shot_dimension), 1)
            if min_shot_dimension is not None
            else max(int(frame_size * 0.000025), 1)
        )

        self.filters_initialized = False

        # diagnostics (unchanged API)
        self.last_candidate_count = 0
        self.last_cluster_count   = 0
        self.last_shot_count      = 0
        self.last_max_lum         = 0
        self.last_max_increase    = 0
        self.last_dynamic_ratio   = 0.0
        self.last_excessive_count = 0

    # ── public helpers ────────────────────────────────────────────────────────

    def set_roi(self, mask: Optional[np.ndarray]):
        """Pass a uint8 mask (255 = detect, 0 = ignore) or None for full frame."""
        self.roi_mask = mask

    def reset(self):
        """Full state reset (e.g. after a scene cut)."""
        self.lums_moving_average[:] = -1
        self.color_distance_from_red[:] = 0
        self.lum_variance[:] = 0
        for buf in self._temporal_buffer:
            buf[:] = 0
        self.avg_threshold_pixels  = -1
        self.filters_initialized   = False
        self.frame_count           = 0
        self.deduplicator.reset()

    # ── luminance computation ─────────────────────────────────────────────────

    def _compute_luminance(self, s: np.ndarray, v: np.ndarray) -> np.ndarray:
        legacy    = (255 - s) * v
        saturated = (s + 1)   * v
        if self.luminance_mode == 'legacy':     return legacy
        if self.luminance_mode == 'saturated':  return saturated
        if self.luminance_mode == 'value':      return v * 255
        if self.luminance_mode == 'adaptive':   return np.maximum(legacy, saturated)
        # 'combined' — weighted blend; laser spots tend to be high-V, any-S
        return (legacy.astype(np.float32) * 0.6 + saturated.astype(np.float32) * 0.4).astype(np.int32)

    # ── moving average period ─────────────────────────────────────────────────

    def _update_period(self, fps: int = 30):
        if self.frame_count % 5 == 0:
            self.moving_average_period = max(int(fps / 5.0), 5)

    # ── main entry point ──────────────────────────────────────────────────────

    def process_frame(self, frame_bgr: np.ndarray, fps: int = 30) -> List[Dict]:
        """
        Returns list of dicts: [{x, y, color, confidence}, …]
        """
        self.frame_count += 1
        self._update_period(fps)

        # ── guard ──────────────────────────────────────────────────────────
        if frame_bgr is None or frame_bgr.size == 0:
            self._zero_diagnostics()
            return []

        if frame_bgr.ndim == 2 or (frame_bgr.ndim == 3 and frame_bgr.shape[2] == 1):
            frame_bgr = cv2.cvtColor(frame_bgr, cv2.COLOR_GRAY2BGR)

        # ── colour space conversion ────────────────────────────────────────
        frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV).astype(np.int32)
        H = frame_hsv[:, :, 0]
        S = frame_hsv[:, :, 1]
        V = frame_hsv[:, :, 2]

        current_lum = self._compute_luminance(S, V)

        h_dist_red   = np.minimum(H, np.abs(180 - H))
        h_dist_green = np.abs(60  - H)
        temp_cdr     = (h_dist_red - h_dist_green) * S * V

        # ── seed uninitialised pixels ──────────────────────────────────────
        uninit = self.lums_moving_average == -1
        if uninit.any():
            self.lums_moving_average[uninit]     = current_lum[uninit]
            self.color_distance_from_red[uninit] = temp_cdr[uninit]
            self._zero_diagnostics()
            return []

        # ── warm-up ────────────────────────────────────────────────────────
        if not self.filters_initialized:
            if self.frame_count > 5:
                self.filters_initialized = True
            self._update_averages(current_lum, temp_cdr)
            self._zero_diagnostics()
            return []

        # ── per-pixel increase ─────────────────────────────────────────────
        increase = current_lum - self.lums_moving_average   # int32

        # ── 1. variance-adaptive threshold ────────────────────────────────
        if self.use_variance_threshold:
            # EMA variance:  var = alpha*(increase - 0)² + (1-alpha)*var
            # (we approximate background variation as deviation from 0 increase)
            deviation              = increase.astype(np.float32)
            self.lum_variance      = (
                self.variance_alpha * deviation ** 2
                + (1 - self.variance_alpha) * self.lum_variance
            )
            std_dev                = np.sqrt(self.lum_variance).astype(np.int32)
            variance_threshold     = (self.variance_k * std_dev).astype(np.int32)
        else:
            variance_threshold = np.zeros_like(increase)

        # ── 2. base dynamic threshold ──────────────────────────────────────
        base_threshold = (self.MAXIMUM_LUM_VALUE - self.lums_moving_average) >> 2

        avg_tp     = self.avg_threshold_pixels if self.avg_threshold_pixels != -1 else 0
        dyn_ratio  = min(avg_tp / max(self.MAXIMUM_THRESHOLD_PIXELS_FOR_AVG, 1),
                         self.max_dynamic_ratio)
        self.last_dynamic_ratio = float(dyn_ratio)

        if self.use_dynamic_threshold:
            dynamic_increase  = ((self.MAXIMUM_LUM_VALUE - base_threshold) * dyn_ratio).astype(np.int32)
            dynamic_threshold = base_threshold + dynamic_increase
        else:
            dynamic_threshold = base_threshold

        # ── 3. combine thresholds ──────────────────────────────────────────
        # A pixel must beat BOTH the dynamic threshold AND its local variance gate
        effective_threshold = np.maximum(dynamic_threshold, variance_threshold)

        # ── 4. masks ───────────────────────────────────────────────────────
        if self.use_excessive_mask:
            excessive_mask = self.lums_moving_average > self.EXCESSIVE_BRIGHTNESS_THRESHOLD
        else:
            excessive_mask = np.zeros((self.feed_height, self.feed_width), dtype=bool)

        self.last_excessive_count = int(excessive_mask.sum())

        # Apply ROI if set
        roi_mask = np.ones((self.feed_height, self.feed_width), dtype=bool)
        if self.roi_mask is not None:
            roi_mask = self.roi_mask > 0

        shot_mask = (
            (increase >= self.MINIMUM_BRIGHTNESS_INCREASE)
            & (increase >= effective_threshold)
            & ~excessive_mask
            & roi_mask
        )

        # ── 5. temporal consistency filter ────────────────────────────────
        current_frame_mask = shot_mask.astype(np.uint8)

        if self.use_temporal_filter and self.temporal_min_frames > 1:
            # Sum how many of the last N frames each pixel fired
            temporal_sum = sum(self._temporal_buffer).astype(np.uint8)
            # Must have fired in at least (temporal_min_frames - 1) previous frames too
            temporal_mask = temporal_sum >= (self.temporal_min_frames - 1)
            shot_mask     = shot_mask & temporal_mask

        # Push current raw mask into ring buffer (before temporal gate)
        self._temporal_buffer.append(current_frame_mask)

        # ── 6. build threshold pixel set ──────────────────────────────────
        ys, xs = np.where(shot_mask)
        threshold_pixels = set()
        for y, x in zip(ys, xs):
            threshold_pixels.add(Pixel(
                x, y,
                color        = int(H[y, x]),
                current_lum  = int(current_lum[y, x]),
                lum_average  = int(self.lums_moving_average[y, x]),
                color_average= int(self.color_distance_from_red[y, x]),
            ))

        # ── 7. update avg threshold pixel count ───────────────────────────
        dyn_thresholded = int(
            np.sum((increase < dynamic_threshold) & (increase > base_threshold))
        )
        total_tp = min(
            len(threshold_pixels) + dyn_thresholded,
            self.MAXIMUM_THRESHOLD_PIXELS_FOR_AVG,
        )
        if self.avg_threshold_pixels == -1:
            self.avg_threshold_pixels = total_tp
        else:
            p = self.moving_average_period
            self.avg_threshold_pixels = int(
                ((p - 1) * self.avg_threshold_pixels + total_tp) / p
            )

        # ── 8. update moving averages ──────────────────────────────────────
        self._update_averages(current_lum, temp_cdr)

        # ── 9. cluster + classify ──────────────────────────────────────────
        self.last_max_lum      = int(current_lum.max()) if current_lum.size else 0
        self.last_max_increase = int(increase.max())    if increase.size    else 0
        self.last_candidate_count = len(threshold_pixels)
        self.last_cluster_count   = 0
        self.last_shot_count      = 0

        if len(threshold_pixels) < self.MINIMUM_SHOT_DIMENSION:
            return []

        clusters = self.pixel_cluster_manager.cluster_pixels(
            threshold_pixels, self.MINIMUM_SHOT_DIMENSION
        )
        self.last_cluster_count = len(clusters)

        shots: List[Dict] = []
        for cluster in clusters:
            color = cluster.get_color(frame_hsv, self.color_distance_from_red)
            if color is None:
                continue

            x, y = cluster.center_pixel_x, cluster.center_pixel_y

            # Deduplication guard
            if self.deduplicator.is_duplicate(x, y):
                continue

            # Confidence score: blend cluster density score + colour certainty
            # + relative increase magnitude
            inc_at_center = float(increase[int(y), int(x)]) if 0 <= int(y) < self.feed_height and 0 <= int(x) < self.feed_width else 0.0
            inc_confidence = min(inc_at_center / (self.MAXIMUM_LUM_VALUE * 0.5), 1.0)
            confidence = round(
                0.4 * cluster.color_confidence
                + 0.6 * inc_confidence,
                3,
            )

            shots.append({
                'x':          x,
                'y':          y,
                'color':      color,
                'confidence': confidence,
            })

        self.last_shot_count = len(shots)
        return shots

    # ── internal helpers ──────────────────────────────────────────────────────

    def _update_averages(self, current_lum: np.ndarray, temp_cdr: np.ndarray):
        p = self.moving_average_period
        self.lums_moving_average = (
            (self.lums_moving_average * (p - 1) + current_lum) // p
        )
        self.color_distance_from_red = (
            (self.color_distance_from_red * (p - 1) + temp_cdr) // p
        )

    def _zero_diagnostics(self):
        self.last_candidate_count = 0
        self.last_cluster_count   = 0
        self.last_shot_count      = 0
        self.last_max_lum         = 0
        self.last_max_increase    = 0
        self.last_dynamic_ratio   = 0.0
        self.last_excessive_count = 0