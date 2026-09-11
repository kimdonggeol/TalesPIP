# -*- coding: utf-8 -*-
"""Turn the positions a config has learned into offsets the build can ship.

The game opens its windows in the middle of the screen and puts the quick-slot
bar a fixed distance up from the bottom left, so where a graphic sits is the
same offset from its corner at every resolution. Record it once and every
resolution is covered.

    python tools/learn_positions.py [config.json]

Reads the found positions out of a config, works out each offset, and merges
them into assets/triggers/positions.json. A condition seen at more than one
resolution is only written when the offsets agree; one that disagrees is
reported instead, since that means it was dragged somewhere while it was
recorded.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSITIONS = os.path.join(ROOT, "assets", "triggers", "positions.json")


def origin(anchor, width, height):
    """The corner an anchor measures from, or the middle when it names none."""
    if anchor in ("l", "tl", "bl"):
        x = 0
    elif anchor in ("r", "tr", "br"):
        x = width
    else:
        x = width // 2
    if anchor in ("t", "tl", "tr"):
        y = 0
    elif anchor in ("b", "bl", "br"):
        y = height
    else:
        y = height // 2
    return x, y


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "config.json")
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    presets = {key: (entry.get("width"), entry.get("height"))
                for key, entry in (config.get("presets") or {}).items()}

    offsets, conflicts = {}, []
    for trigger in (config.get("auto_hide") or {}).get("triggers") or []:
        key = trigger.get("builtin")
        if not key:
            continue
        anchor = trigger.get("anchor", "all")
        seen = set()
        for preset, spot in (trigger.get("found") or {}).items():
            width, height = presets.get(preset, (None, None))
            if not (width and height):
                continue
            ox, oy = origin(anchor, width, height)
            seen.add((spot[0] - ox, spot[1] - oy))
        if not seen:
            continue
        if len(seen) > 1:
            conflicts.append((key, sorted(seen)))
            continue
        dx, dy = seen.pop()
        offsets[key] = {"anchor": anchor, "dx": dx, "dy": dy}

    kept = {}
    if os.path.exists(POSITIONS):
        with open(POSITIONS, encoding="utf-8") as f:
            kept = json.load(f)
    added = [k for k in offsets if k not in kept]
    changed = [k for k in offsets if k in kept and kept[k] != offsets[k]]
    kept.update(offsets)
    os.makedirs(os.path.dirname(POSITIONS), exist_ok=True)
    with open(POSITIONS, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(kept.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"{len(kept)} offsets in {os.path.relpath(POSITIONS, ROOT)}")
    print(f"  {len(added)} new, {len(changed)} updated")
    for key in sorted(added):
        entry = kept[key]
        print(f"    + {key:28s} {entry['anchor']:4s} {entry['dx']:5d}, {entry['dy']:5d}")
    for key in sorted(changed):
        entry = kept[key]
        print(f"    ~ {key:28s} {entry['anchor']:4s} {entry['dx']:5d}, {entry['dy']:5d}")
    for key, seen in conflicts:
        print(f"    ! {key} was in different places at different resolutions: {seen}")
        print("      it was probably dragged while being recorded; record it again")


if __name__ == "__main__":
    main()
