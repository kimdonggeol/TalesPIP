# -*- coding: utf-8 -*-
"""Score every built-in condition against the game's screen right now.

Open the window you want to check in the game, then run this. It prints how
well each condition matches and where, so you can see which ones are found,
which are close, and which are nowhere near.

    python tools/check_triggers.py
    python tools/check_triggers.py itemshop        # just the ones named

A score at or above the threshold counts as found. A condition that is not on
screen usually lands between 0.3 and 0.7, so anything in between is a warning
that the image needs a better crop.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication(sys.argv)

import tales_pip as m  # noqa: E402


def main():
    wanted = [a.lower() for a in sys.argv[1:]]
    if not m.MATCHING_AVAILABLE:
        sys.exit("numpy and opencv are needed for screen matching")
    windows = [h for h, _, p in m.list_visible_windows()
                if p.lower() == m.TARGET_PROCESS.lower()]
    if not windows:
        sys.exit(f"{m.TARGET_LABEL} is not running")
    hwnd = windows[0]
    left, top, right, bottom = m.get_client_rect_on_screen(hwnd)
    width, height = right - left, bottom - top
    frame = m.to_gray(m.grab_client(hwnd, 0, 0, width, height))
    if frame is None:
        sys.exit("could not read the game window")
    threshold = m.DEFAULT_AUTO_HIDE["threshold"] / 100.0
    print(f"client {width}x{height}, threshold {threshold:.2f}\n")
    print(f"{'condition':14s} {'mode':5s} {'anchor':6s} {'size':>9s} "
          f"{'in anchor':>10s} {'anywhere':>9s}  position")

    rows = []
    for key, label, mode, anchor in m.builtin_trigger_files():
        if wanted and not any(w in label.lower() for w in wanted):
            continue
        path = m.builtin_trigger_path(key)
        template = m.to_gray(m.read_image(path)) if path else None
        if template is None:
            print(f"{label:14s} could not be read")
            continue
        ax, ay, aw, ah = m.anchor_box(anchor, width, height)
        area = frame[ay:ay + ah, ax:ax + aw]
        inside = m.best_match(area, template)
        anywhere = m.best_match(frame, template)
        th, tw = template.shape
        mark = "  FOUND" if anywhere and anywhere[0] >= threshold else ""
        where = f"({anywhere[1]}, {anywhere[2]})" if anywhere else "-"
        outside = ""
        # Only worth saying when the match is plausible; with nothing on screen
        # the best score lands somewhere arbitrary and means nothing.
        if (anywhere and inside and anywhere[0] >= 0.7
                and anywhere[0] - inside[0] > 0.05):
            outside = "  <- better outside its anchor"
        print(f"{label:14s} {mode:5s} {anchor:6s} {tw:4d}x{th:<4d} "
              f"{inside[0] if inside else 0:10.3f} {anywhere[0]:9.3f}  "
              f"{where}{mark}{outside}")
        rows.append((label, anywhere[0]))

    if rows:
        worst = max(rows, key=lambda r: r[1])
        print(f"\nhighest score: {worst[0]} at {worst[1]:.3f}")


if __name__ == "__main__":
    main()
