import subprocess
from pathlib import Path

import cv2

# Target test pages (1-indexed matching PDF page numbers)
TEST_PAGES = [9, 113, 179, 180, 213, 216]
PDF_FILE = "src-py/tests/fixtures/scans/The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf"
OUT_DIR = Path("./matrix_test")
OUT_DIR.mkdir(exist_ok=True)


def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)


def apply_adaptive_threshold(img_path):
    """Applies dynamic localized thresholding to handle lighting gradients and faint text."""
    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)

    # Gaussian Adaptive Thresholding handles localized illumination gradients well
    adaptive_gaussian = cv2.adaptiveThreshold(
        img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=31, C=15
    )
    return adaptive_gaussian


# Extract raw images via pdfimages and flattened pages via pdftoppm for test subset
for p in TEST_PAGES:
    prefix = OUT_DIR / f"page_{p}"

    # 1. Extract raw streams
    run_cmd(f"pdfimages -png -f {p} -l {p} '{PDF_FILE}' '{prefix}_stream'")

    # 2. Render flat full-color page at 300 DPI
    run_cmd(f"pdftoppm -png -r 300 -f {p} -l {p} '{PDF_FILE}' '{prefix}_flat'")

# Execute Pipeline Matrix
for p in TEST_PAGES:
    prefix = OUT_DIR / f"page_{p}"
    raw_mask = list(OUT_DIR.glob(f"page_{p}_stream-*.png"))[
        -1
    ]  # Target the 1-bit foreground mask
    flat_page = list(OUT_DIR.glob(f"page_{p}_flat-*.png"))[0]

    # Pipeline 1: Raw Mask -> Invert -> Adaptive Threshold -> Unpaper
    inv_mask = cv2.bitwise_not(cv2.imread(str(raw_mask), cv2.IMREAD_GRAYSCALE))
    thresh1 = cv2.adaptiveThreshold(
        inv_mask, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    cv2.imwrite(str(OUT_DIR / f"p{p}_pipe1_thresh_first.png"), thresh1)
    run_cmd(
        f"unpaper --layout single '{OUT_DIR}/p{p}_pipe1_thresh_first.png' '{OUT_DIR}/p{p}_pipe1_final.png'"
    )

    # Pipeline 2: Raw Mask -> Invert -> Unpaper -> Adaptive Threshold
    cv2.imwrite(str(OUT_DIR / f"p{p}_pipe2_raw_inv.png"), inv_mask)
    run_cmd(
        f"unpaper --layout single '{OUT_DIR}/p{p}_pipe2_raw_inv.png' '{OUT_DIR}/p{p}_pipe2_unpapered.png'"
    )
    pipe2_final = apply_adaptive_threshold(OUT_DIR / f"p{p}_pipe2_unpapered.png")
    cv2.imwrite(str(OUT_DIR / f"p{p}_pipe2_final.png"), pipe2_final)

    # Pipeline 3: Flat Render -> Adaptive Threshold (Otsu/Local) -> Unpaper
    flat_gray = cv2.imread(str(flat_page), cv2.IMREAD_GRAYSCALE)
    _, otsu = cv2.threshold(flat_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite(str(OUT_DIR / f"p{p}_pipe3_otsu.png"), otsu)
    run_cmd(
        f"unpaper --layout single '{OUT_DIR}/p{p}_pipe3_otsu.png' '{OUT_DIR}/p{p}_pipe3_final.png'"
    )

    # Pipeline 4: Composite Layer (Background + Inverted Mask) -> Adaptive Threshold
    # Useful for preserving faint strokes on light pages like 179
    bg_img = list(OUT_DIR.glob(f"page_{p}_stream-000.png"))[0]
    run_cmd(
        f"magick '{bg_img}' -resize 2358x4140! \\( '{raw_mask}' -negate \\) -compose multiply -composite '{OUT_DIR}/p{p}_pipe4_comp.png'"
    )
    pipe4_final = apply_adaptive_threshold(OUT_DIR / f"p{p}_pipe4_comp.png")
    cv2.imwrite(str(OUT_DIR / f"p{p}_pipe4_final.png"), pipe4_final)

print("Matrix test execution complete. Inspect results in ./matrix_test/")
