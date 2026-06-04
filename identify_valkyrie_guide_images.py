#!/usr/bin/env python3
import argparse
import csv
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parent
GUIDE_DIR = Path(r"D:\code\HoshinoBot\res\img\ElysianRealm")
VALKYRIE_DATA = BASE_DIR / "data/bh3_valkyries_with_local_images.json"
REPORT_PATH = BASE_DIR / "data/elysian_realm_guide_image_matches.csv"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip()
    return value or "unknown"


def imread_unicode(path, flags=cv2.IMREAD_UNCHANGED):
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None:
        raise RuntimeError(f"Failed to read image: {path}")
    return image


def image_size(path):
    image = imread_unicode(path, cv2.IMREAD_COLOR)
    h, w = image.shape[:2]
    return w, h


def crop_poster(path):
    image = imread_unicode(path, cv2.IMREAD_UNCHANGED)
    if image.shape[2] == 4:
        alpha = image[:, :, 3]
        points = cv2.findNonZero((alpha > 8).astype(np.uint8))
        x, y, w, h = cv2.boundingRect(points)
        image = image[y:y + h, x:x + w]
        mask = image[:, :, 3]
        bgr = image[:, :, :3]
    else:
        bgr = image[:, :, :3]
        mask = np.full(bgr.shape[:2], 255, dtype=np.uint8)

    # The guide card mostly shows the upper body/head. Dropping the lower body
    # reduces false matches caused by weapons and long coat tails.
    keep_h = int(bgr.shape[0] * 0.82)
    bgr = bgr[:keep_h, :]
    mask = mask[:keep_h, :]

    max_side = max(bgr.shape[:2])
    if max_side > 900:
        scale = 900 / max_side
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    return bgr, mask


def crop_guide_roi(path):
    image = imread_unicode(path, cv2.IMREAD_COLOR)
    h, w = image.shape[:2]
    # Upper-left portrait card. Includes the tilted character art while avoiding
    # most of the right-side difficulty panel.
    x1, y1 = int(w * 0.035), int(h * 0.015)
    x2, y2 = int(w * 0.61), int(h * 0.285)
    roi = image[y1:y2, x1:x2]
    max_side = max(roi.shape[:2])
    if max_side > 700:
        scale = 700 / max_side
        roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return roi


def make_detector():
    return cv2.AKAZE_create(
        descriptor_type=cv2.AKAZE_DESCRIPTOR_MLDB,
        threshold=0.00045,
        nOctaves=5,
        nOctaveLayers=4,
    )


def preprocess_for_features(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.equalizeHist(gray)


def extract_features(detector, bgr, mask=None):
    gray = preprocess_for_features(bgr)
    if mask is not None:
        mask = (mask > 8).astype(np.uint8) * 255
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.erode(mask, kernel, iterations=1)
    kp, desc = detector.detectAndCompute(gray, mask)
    return kp, desc


def build_poster_index(rows):
    detector = make_detector()
    indexed = []
    for row in rows:
        bgr, mask = crop_poster(row["poster_image_local"])
        kp, desc = extract_features(detector, bgr, mask)
        indexed.append({**row, "keypoints": kp, "descriptors": desc})
    return detector, indexed


def score_match(matcher, guide_kp, guide_desc, poster):
    desc = poster["descriptors"]
    kp = poster["keypoints"]
    if guide_desc is None or desc is None or len(guide_desc) < 8 or len(desc) < 8:
        return 0.0, 0, 0, 0

    raw = matcher.knnMatch(desc, guide_desc, k=2)
    good = []
    for pair in raw:
        if len(pair) < 2:
            continue
        first, second = pair
        if first.distance < 0.76 * second.distance:
            good.append(first)

    if len(good) < 6:
        return float(len(good)), len(good), 0, len(desc)

    src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([guide_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0

    avg_distance = sum(m.distance for m in good) / len(good)
    score = inliers * 4.0 + len(good) * 0.9 + max(0.0, 90.0 - avg_distance) * 0.08
    return score, len(good), inliers, len(desc)


def best_matches(guide_path, detector, posters):
    roi = crop_guide_roi(guide_path)
    guide_kp, guide_desc = extract_features(detector, roi)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    scored = []
    for poster in posters:
        score, good, inliers, feature_count = score_match(matcher, guide_kp, guide_desc, poster)
        scored.append({
            "name": poster["name"],
            "content_id": poster["content_id"],
            "score": score,
            "good_matches": good,
            "inliers": inliers,
            "feature_count": feature_count,
        })
    scored.sort(key=lambda item: (item["score"], item["inliers"], item["good_matches"]), reverse=True)
    return scored


def next_available_path(path):
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def already_named_for_match(path, matched_name):
    suffix = re.escape(path.suffix)
    stem = re.escape(safe_name(matched_name))
    return re.fullmatch(rf"{stem}(?:_\d+)?{suffix}", path.name) is not None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--guide-dir", type=Path, default=GUIDE_DIR, help="directory containing guide images")
    parser.add_argument("--report", type=Path, default=REPORT_PATH, help="CSV match report path")
    parser.add_argument("--rename", action="store_true", help="rename guide images after matching")
    parser.add_argument("--threshold", type=float, default=35.0)
    parser.add_argument("--margin", type=float, default=8.0)
    args = parser.parse_args()

    rows = json.loads(VALKYRIE_DATA.read_text(encoding="utf-8"))
    detector, posters = build_poster_index(rows)
    guide_paths = sorted(
        p
        for p in args.guide_dir.iterdir()
        if p.is_file() and p.name.lower() != "404.jpg" and p.suffix.lower() in IMAGE_SUFFIXES
    )

    report = []
    for guide_path in guide_paths:
        matches = best_matches(guide_path, detector, posters)
        best = matches[0]
        second = matches[1]
        margin = best["score"] - second["score"]
        width, height = image_size(guide_path)
        portrait_guide = height / max(width, 1) >= 1.25

        renamed = False
        new_path = ""
        confident = portrait_guide and best["score"] >= args.threshold and margin >= args.margin
        if args.rename:
            if confident:
                target = guide_path.with_name(f"{safe_name(best['name'])}{guide_path.suffix.lower()}")
                if already_named_for_match(guide_path, best["name"]):
                    new_path = str(guide_path)
                else:
                    target = next_available_path(target)
                    guide_path.rename(target)
                    renamed = True
                    new_path = str(target)
            elif not portrait_guide and not guide_path.name.startswith("00_"):
                target = next_available_path(guide_path.with_name(f"00_总览{guide_path.suffix.lower()}"))
                guide_path.rename(target)
                renamed = True
                new_path = str(target)

        report.append({
            "file": str(guide_path),
            "width": width,
            "height": height,
            "portrait_guide": portrait_guide,
            "matched_name": best["name"],
            "content_id": best["content_id"],
            "score": f"{best['score']:.2f}",
            "good_matches": best["good_matches"],
            "inliers": best["inliers"],
            "second_name": second["name"],
            "second_score": f"{second['score']:.2f}",
            "second_good_matches": second["good_matches"],
            "second_inliers": second["inliers"],
            "margin": f"{margin:.2f}",
            "confident": confident,
            "renamed": renamed,
            "new_path": new_path,
        })
        print(
            f"{guide_path.name}: {best['name']} "
            f"score={best['score']:.2f} inliers={best['inliers']} "
            f"second={second['name']} margin={margin:.2f} portrait={portrait_guide} confident={confident}"
        )

    if not report:
        print(f"No images found in {args.guide_dir}")
        return

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=report[0].keys())
        writer.writeheader()
        writer.writerows(report)

    print(f"\nWrote {args.report}")


if __name__ == "__main__":
    main()
