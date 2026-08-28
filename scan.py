"""Phase 1: standalone scan pipeline — image in, scanned-look image out.

Usage:
    python scan.py input.jpg output.jpg [--filter original|photo|docs|clear] [--bw]
"""
import argparse
import sys

import cv2

from clearscanner.core import detector, filters, transform


def scan_image(image_path: str, filter_mode: str = "clear", bw: bool = False):
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    corners = detector.find_document_contour(image)
    if corners is None:
        print("No document contour found — falling back to full image.")
        corners = detector.full_image_corners(image)

    warped = transform.four_point_transform(image, corners)
    return filters.apply_filter(warped, filter_mode, bw=bw)


def main():
    parser = argparse.ArgumentParser(description="Scan a document photo.")
    parser.add_argument("input", help="path to input image")
    parser.add_argument("output", help="path to write scanned output image")
    parser.add_argument(
        "--filter", choices=filters.COLOR_MODES, default="clear", help="color mode"
    )
    parser.add_argument("--bw", action="store_true", help="render monochrome instead of --filter")
    args = parser.parse_args()

    result = scan_image(args.input, args.filter, bw=args.bw)
    if not cv2.imwrite(args.output, result):
        print(f"Failed to write output: {args.output}", file=sys.stderr)
        sys.exit(1)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
