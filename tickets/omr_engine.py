"""
OMR (Optical Mark Recognition) Engine for the ICT Helpdesk JRF Scanner.

This module processes a photograph of a printed Job Request Form and extracts
the shaded performance indicator scores (Quality, Efficiency, Timeliness)
using OpenCV contour detection and pixel analysis.

Pipeline:
    1. Decode image bytes → OpenCV Mat
    2. Grayscale → Gaussian Blur → Otsu's threshold
    3. Detect the 4 black alignment markers (corners of the OMR region)
    4. Apply a 4-point perspective transform to flatten the ROI
    5. Re-threshold the warped ROI
    6. Detect circular contours (the bubbles)
    7. Sort into 3 rows × 5 columns, count dark pixels per bubble
    8. Return {"quality": X, "efficiency": Y, "timeliness": Z}
"""

import cv2
import numpy as np


def order_points(pts):
    """
    Order 4 points as: top-left, top-right, bottom-right, bottom-left.
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]      # top-left has smallest x+y
    rect[2] = pts[np.argmax(s)]      # bottom-right has largest x+y
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]   # top-right has smallest x-y
    rect[3] = pts[np.argmax(diff)]   # bottom-left has largest x-y
    return rect


def four_point_transform(image, pts):
    """
    Apply a perspective transform using 4 ordered corner points.
    """
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = max(int(widthA), int(widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = max(int(heightA), int(heightB))

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def find_alignment_markers(thresh, min_area=200, max_area=5000):
    """
    Find the 4 solid black square alignment markers using contour detection.
    Returns the center points of the 4 best candidates.
    """
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area < area < max_area:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            # Squares have 4 vertices
            if len(approx) == 4:
                x, y, w, h = cv2.boundingRect(approx)
                aspect_ratio = w / float(h) if h > 0 else 0
                # Aspect ratio of a square is close to 1.0
                if 0.7 <= aspect_ratio <= 1.3:
                    cx = x + w // 2
                    cy = y + h // 2
                    candidates.append((cx, cy, area, cnt))

    if len(candidates) < 4:
        return None

    # Sort by area descending and pick the 4 largest square-like contours
    candidates.sort(key=lambda c: c[2], reverse=True)
    top4 = candidates[:4]

    centers = np.array([[c[0], c[1]] for c in top4], dtype="float32")
    return centers


def find_bubbles_in_roi(warped_thresh, rows=3, cols=5):
    """
    Find circular contours in the warped (flattened) OMR region.
    Sort them into a grid of `rows` × `cols` and determine which
    bubble is shaded in each row.

    Returns a dict: {"quality": X, "efficiency": Y, "timeliness": Z}
    """
    contours, _ = cv2.findContours(warped_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = warped_thresh.shape
    min_bubble_area = (h * w) / 500  # Dynamic minimum based on image size
    max_bubble_area = (h * w) / 20

    bubble_candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_bubble_area < area < max_bubble_area:
            peri = cv2.arcLength(cnt, True)
            circularity = (4 * np.pi * area) / (peri * peri) if peri > 0 else 0
            if circularity > 0.5:  # Reasonably circular
                (cx, cy), radius = cv2.minEnclosingCircle(cnt)
                bubble_candidates.append({
                    'cx': cx, 'cy': cy, 'radius': radius,
                    'contour': cnt, 'area': area
                })

    if len(bubble_candidates) < rows * cols:
        return None

    # Sort by Y coordinate first (to separate rows), then X (to order columns)
    bubble_candidates.sort(key=lambda b: b['cy'])

    # Divide into rows
    row_size = len(bubble_candidates) // rows
    bubble_rows = []
    for i in range(rows):
        start = i * row_size
        end = start + row_size if i < rows - 1 else len(bubble_candidates)
        row = bubble_candidates[start:end]
        # Sort each row by X coordinate (left to right)
        row.sort(key=lambda b: b['cx'])
        # Take only the expected number of columns
        bubble_rows.append(row[:cols])

    # Analyze which bubble is shaded in each row
    score_labels = ['quality', 'efficiency', 'timeliness']
    # Columns are ordered 5, 4, 3, 2, 1 (left to right)
    column_values = [5, 4, 3, 2, 1]
    results = {}

    for row_idx, row in enumerate(bubble_rows):
        if row_idx >= len(score_labels):
            break

        max_filled = 0
        selected_col = 2  # Default to middle score (3) if detection fails

        for col_idx, bubble in enumerate(row):
            # Create a mask for this bubble
            mask = np.zeros(warped_thresh.shape, dtype="uint8")
            cv2.circle(mask, (int(bubble['cx']), int(bubble['cy'])),
                       int(bubble['radius'] * 0.7), 255, -1)

            # Count dark pixels (shaded area) within the bubble mask
            # In thresholded image, dark = 0 (inverted), so we invert
            inverted = cv2.bitwise_not(warped_thresh)
            filled = cv2.countNonZero(cv2.bitwise_and(inverted, inverted, mask=mask))

            if filled > max_filled:
                max_filled = filled
                selected_col = col_idx

        score = column_values[selected_col] if selected_col < len(column_values) else 3
        results[score_labels[row_idx]] = score

    return results


def process_omr_image(image_bytes):
    """
    Main entry point. Accepts raw image bytes (e.g. JPEG from camera capture),
    processes the OMR region, and returns extracted scores.

    Returns:
        dict: {"quality": int, "efficiency": int, "timeliness": int}
              or None if processing fails.
    """
    # 1. Decode image bytes into an OpenCV image
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        return None

    # 2. Convert to grayscale, blur, and threshold
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 3. Find the 4 alignment markers
    markers = find_alignment_markers(thresh)
    if markers is None:
        return None

    # 4. Apply perspective transform to flatten the OMR region
    warped = four_point_transform(gray, markers)

    # 5. Re-threshold the warped image
    _, warped_thresh = cv2.threshold(warped, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 6-7. Find and analyze bubbles
    scores = find_bubbles_in_roi(warped_thresh)
    return scores
