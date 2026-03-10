"""
Card Scanner — Image Preprocessing
═══════════════════════════════════

Handles:
  - Loading images from bytes
  - Detecting card-shaped quadrilaterals via contour analysis
  - Perspective-warping detected cards to a flat rectangle
  - Cropping the title bar region for OCR
"""
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None
    print("WARNING: opencv-python not installed. Card scanning will be unavailable.")
    print("  Install with: pip install opencv-python")


# Standard MTG card aspect ratio ≈ 63mm × 88mm ≈ 0.716
CARD_ASPECT_RATIO = 0.716
ASPECT_TOLERANCE = 0.25  # ± tolerance for aspect ratio matching

# Target warped card size (pixels)
WARPED_WIDTH = 480
WARPED_HEIGHT = int(WARPED_WIDTH / CARD_ASPECT_RATIO)  # ~670

# Title bar crop: top ~8% of the card height
TITLE_TOP_FRAC = 0.03
TITLE_BOTTOM_FRAC = 0.11
TITLE_LEFT_FRAC = 0.05
TITLE_RIGHT_FRAC = 0.82


def load_image_from_bytes(image_bytes: bytes) -> "np.ndarray":
    """Decode image bytes (JPEG, PNG, etc.) into a BGR numpy array."""
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image from provided bytes")
    return img


def find_card_quads(image: "np.ndarray", min_area_frac: float = 0.005, max_area_frac: float = 0.5) -> list:
    """
    Find card-shaped quadrilaterals in the image.

    Returns a list of 4-point contours (np.ndarray of shape (4,2)) sorted
    left-to-right, top-to-bottom for consistent ordering.

    Args:
        image: BGR input image
        min_area_frac: Minimum contour area as a fraction of total image area
        max_area_frac: Maximum contour area as a fraction of total image area
    """
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")

    h, w = image.shape[:2]
    total_area = h * w
    min_area = total_area * min_area_frac
    max_area = total_area * max_area_frac

    # Convert to grayscale and blur
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Try multiple edge detection approaches for robustness
    quads = []

    # Approach 1: Canny edge detection
    edges = cv2.Canny(blurred, 50, 150)
    # Dilate to close gaps in edges
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    quads.extend(_find_quads_from_edges(edges, min_area, max_area))

    # Approach 2: Adaptive threshold (catches cards with low contrast borders)
    if len(quads) == 0:
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        thresh = cv2.bitwise_not(thresh)
        quads.extend(_find_quads_from_edges(thresh, min_area, max_area))

    # Deduplicate overlapping quads
    quads = _deduplicate_quads(quads)

    # Sort: top-to-bottom, then left-to-right
    quads.sort(key=lambda q: (q[:, 1].mean(), q[:, 0].mean()))

    return quads


def _find_quads_from_edges(edges: "np.ndarray", min_area: float, max_area: float) -> list:
    """Extract 4-point polygons from an edge/threshold image."""
    if cv2 is None:
        return []

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

        if len(approx) == 4 and cv2.isContourConvex(approx):
            pts = approx.reshape(4, 2).astype(np.float32)
            # Check aspect ratio
            rect = cv2.minAreaRect(approx)
            (_, (rw, rh), _) = rect
            if rw == 0 or rh == 0:
                continue
            aspect = min(rw, rh) / max(rw, rh)
            if abs(aspect - CARD_ASPECT_RATIO) < ASPECT_TOLERANCE:
                quads.append(pts)

    return quads


def _deduplicate_quads(quads: list, overlap_threshold: float = 50.0) -> list:
    """Remove quads whose centers are too close to each other."""
    if len(quads) <= 1:
        return quads

    result = []
    centers = []
    for q in quads:
        cx, cy = q[:, 0].mean(), q[:, 1].mean()
        # Check if this center is too close to an existing one
        too_close = False
        for (ex, ey) in centers:
            if abs(cx - ex) < overlap_threshold and abs(cy - ey) < overlap_threshold:
                too_close = True
                break
        if not too_close:
            result.append(q)
            centers.append((cx, cy))

    return result


def _order_points(pts: "np.ndarray") -> "np.ndarray":
    """
    Order 4 points as: top-left, top-right, bottom-right, bottom-left.
    This is required for correct perspective transform.
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left has smallest sum
    rect[2] = pts[np.argmax(s)]  # bottom-right has largest sum
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]  # top-right has smallest difference
    rect[3] = pts[np.argmax(d)]  # bottom-left has largest difference
    return rect


def warp_card(image: "np.ndarray", quad: "np.ndarray") -> "np.ndarray":
    """
    Apply perspective transform to extract a flat, rectangular card image.

    Args:
        image: Source BGR image
        quad: 4-point polygon (shape (4,2))

    Returns:
        Warped card image of size WARPED_WIDTH × WARPED_HEIGHT
    """
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")

    ordered = _order_points(quad)
    dst = np.array([
        [0, 0],
        [WARPED_WIDTH - 1, 0],
        [WARPED_WIDTH - 1, WARPED_HEIGHT - 1],
        [0, WARPED_HEIGHT - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(image, M, (WARPED_WIDTH, WARPED_HEIGHT))

    # Check if card is upside down (title bar should be at top)
    # Compare brightness of top vs bottom strips — title bar is typically lighter
    top_strip = warped[:WARPED_HEIGHT // 6, :]
    bot_strip = warped[-WARPED_HEIGHT // 6:, :]
    if top_strip.mean() < bot_strip.mean() - 10:
        # Likely upside down, rotate 180°
        warped = cv2.rotate(warped, cv2.ROTATE_180)

    return warped


def extract_title_bar(card_img: "np.ndarray") -> "np.ndarray":
    """
    Crop the title bar region from a warped card image.

    The title bar is approximately the top 3–11% of the card,
    inset slightly from left/right edges to avoid border artifacts.
    """
    h, w = card_img.shape[:2]
    y1 = int(h * TITLE_TOP_FRAC)
    y2 = int(h * TITLE_BOTTOM_FRAC)
    x1 = int(w * TITLE_LEFT_FRAC)
    x2 = int(w * TITLE_RIGHT_FRAC)
    return card_img[y1:y2, x1:x2]
