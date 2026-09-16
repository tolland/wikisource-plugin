import cv2


def fix_fold_and_gradient(image_path, crop_left_percent=0.08):
    """
    1. Removes edge scanner artifacts by cropping outer 8%.
    2. Uses morphological closing to estimate background illumination and division-normalize it.
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape

    # 1. Hard crop outer scanning margins (adjust crop_left_percent for gutter width)
    left_bound = int(w * crop_left_percent)
    cropped = img[:, left_bound:w]

    # 2. Divide out the background illumination gradient (flattens dark folds)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (51, 51))
    background = cv2.morphologyEx(cropped, cv2.MORPH_CLOSE, kernel)

    # Normalize background: (img / background) * 255
    normalized = cv2.divide(cropped, background, scale=255)

    # 3. Apply Gaussian Adaptive Thresholding to the normalized image
    cleaned = cv2.adaptiveThreshold(
        normalized,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10,
    )
    return cleaned


# Save cleaned output for Page 179
cv2.imwrite(
    "p179_flattened_clean.png",
    fix_fold_and_gradient("matrix_test/page_179_flat-179.png"),
)
