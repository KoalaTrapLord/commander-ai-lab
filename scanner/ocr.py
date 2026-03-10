"""
Card Scanner — OCR (Optical Character Recognition)
═══════════════════════════════════════════════════

Reads card titles from cropped title bar images using Tesseract OCR.
Includes preprocessing (threshold, denoise, sharpen) to improve accuracy.
"""
import re
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pytesseract
except ImportError:
    pytesseract = None
    print("WARNING: pytesseract not installed. Card scanning will be unavailable.")
    print("  Install with: pip install pytesseract")
    print("  Also install Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki")


# Characters that are legal in MTG card names
_CARD_NAME_CHARS = re.compile(r"[^a-zA-Z0-9\s',\-/]")


def read_title(image: "np.ndarray") -> str:
    """
    Read the card title from a cropped title bar image.

    Applies preprocessing (grayscale, resize, sharpen, threshold) then OCR.
    Returns cleaned text string, or empty string on failure.
    """
    if cv2 is None or pytesseract is None:
        return ""

    try:
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # Upscale for better OCR accuracy (Tesseract works best at ~300 DPI)
        h, w = gray.shape[:2]
        if w < 600:
            scale = 600 / w
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray, h=10)

        # Sharpen — makes letter edges crisper for OCR
        sharpen_kernel = np.array([[-1, -1, -1],
                                   [-1,  9, -1],
                                   [-1, -1, -1]])
        sharpened = cv2.filter2D(denoised, -1, sharpen_kernel)

        # Build candidate images with various preprocessing
        candidates = []

        # 1. Otsu threshold on sharpened
        _, otsu = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates.append(otsu)

        # 2. Inverted Otsu (dark cards with light text)
        candidates.append(cv2.bitwise_not(otsu))

        # 3. Adaptive threshold on sharpened
        adaptive = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY, 21, 6)
        candidates.append(adaptive)

        # 4. High-contrast threshold (typical white/cream title bars)
        _, hi = cv2.threshold(sharpened, 160, 255, cv2.THRESH_BINARY)
        candidates.append(hi)

        # 5. Denoised grayscale (let Tesseract do its own binarization)
        candidates.append(denoised)

        # 6. CLAHE enhanced + Otsu (handles uneven lighting)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        _, clahe_otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates.append(clahe_otsu)

        # 7. Morphological close then Otsu (connects broken letter strokes)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        closed = cv2.morphologyEx(sharpened, cv2.MORPH_CLOSE, kernel)
        _, morph_otsu = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates.append(morph_otsu)

        # PSM configs optimized for card titles:
        #   7 = single text line
        #  13 = raw line (no dictionaries)
        #   8 = single word (for short card names)
        configs = [
            "--psm 7 --oem 3",
            "--psm 13 --oem 3",
            "--psm 8 --oem 3",
        ]

        best_text = ""
        best_conf = 0.0

        for cfg in configs:
            for img in candidates:
                try:
                    data = pytesseract.image_to_data(img, config=cfg, output_type=pytesseract.Output.DICT)
                    texts = []
                    confs = []
                    for i, txt in enumerate(data["text"]):
                        txt = txt.strip()
                        conf = int(data["conf"][i]) if str(data["conf"][i]) != "-1" else 0
                        if txt and conf > 15:
                            texts.append(txt)
                            confs.append(conf)

                    if texts:
                        full_text = " ".join(texts)
                        avg_conf = sum(confs) / len(confs)
                        # Bonus for results that look like card names (mostly alpha)
                        alpha_ratio = sum(1 for c in full_text if c.isalpha()) / max(len(full_text), 1)
                        adjusted_conf = avg_conf * (0.5 + 0.5 * alpha_ratio)
                        if adjusted_conf > best_conf:
                            best_conf = adjusted_conf
                            best_text = full_text
                except Exception:
                    continue

        return _clean_ocr_text(best_text)

    except Exception:
        return ""


def _clean_ocr_text(text: str) -> str:
    """
    Clean OCR output to produce a valid card name.

    Fixes common OCR artifacts and normalizes whitespace.
    """
    if not text:
        return ""

    # Remove leading/trailing whitespace and newlines
    text = text.strip().replace("\n", " ").replace("\r", "")

    # Common OCR substitutions for card text
    # l/I confusion, 0/O confusion, etc.
    replacements = {
        "|": "l",
        "¢": "c",
        "©": "c",
        "®": "",
        "™": "",
        "€": "e",
        "£": "",
        "¥": "",
        "§": "s",
        "°": "o",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove common OCR artifacts (keep letters, digits, spaces, apostrophes, commas, hyphens)
    text = _CARD_NAME_CHARS.sub("", text)

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    # Remove leading/trailing punctuation (except apostrophes mid-word)
    text = text.strip(" ,.-/")

    # Remove very short results (likely noise)
    if len(text) < 2:
        return ""

    return text
