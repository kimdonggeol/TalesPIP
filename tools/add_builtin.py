# -*- coding: utf-8 -*-
"""Install an image as a condition that ships with the build.

    python tools/add_builtin.py 퀵슬롯.png --mode show --anchor bl
    python tools/add_builtin.py market.png --mode hide --anchor c --name 오픈마켓

mode   show = this graphic must be on screen for PIPs to appear
       hide = this graphic on screen hides the PIPs
anchor where to look: all tl t tr l c r bl b br  (default all)
name   what it is called internally (default: the file name)

The file lands in assets/triggers/<mode>/<name>@<anchor>.png and the next
build picks it up. These conditions never appear in the settings window.
"""
import argparse
import os
import re
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "triggers")
ANCHORS = ("all", "tl", "t", "tr", "l", "c", "r", "bl", "b", "br")
MIN_DETAIL = 6.0        # matches MIN_TRIGGER_DETAIL in tales_pip.py
MIN_SCALE_SIDE = 48     # below this a sweep runs at full resolution


def safe_name(name):
    cleaned = re.sub(r"[^0-9A-Za-z가-힣 _-]", "", name).strip().replace(" ", "_")
    return cleaned or "trigger"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--mode", choices=("show", "hide"), required=True)
    parser.add_argument("--anchor", choices=ANCHORS, default="all")
    parser.add_argument("--name")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        sys.exit(f"no such file: {args.image}")
    image = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        sys.exit(f"could not read {args.image} as an image")

    height, width = image.shape[:2]
    detail = float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).std())
    if detail < MIN_DETAIL:
        sys.exit(f"too plain to tell apart from anything else (detail {detail:.1f}, "
                 f"needs {MIN_DETAIL}). Crop to a part with text or an edge in it.")

    name = safe_name(args.name or os.path.splitext(os.path.basename(args.image))[0])
    folder = os.path.join(OUT_DIR, args.mode)
    os.makedirs(folder, exist_ok=True)
    suffix = "" if args.anchor == "all" else f"@{args.anchor}"
    path = os.path.join(folder, f"{name}{suffix}.png")
    cv2.imencode(".png", image)[1].tofile(path)

    print(f"wrote {os.path.relpath(path, ROOT)}")
    print(f"  {width}x{height}, detail {detail:.1f}")
    if min(height, width) < MIN_SCALE_SIDE and args.anchor == "all":
        print("  note: a graphic this thin is searched at full size, and with no "
              "anchor that means sweeping the whole screen. Pass --anchor.")


if __name__ == "__main__":
    main()
