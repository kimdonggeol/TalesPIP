# -*- coding: utf-8 -*-
"""Turn triggers captured in the app into images the build can ship.

Capture the graphics in TalesPIP first (설정 > 자동 숨김 > 화면에서 추가), then
run this. Every user trigger in config.json is written to assets/triggers/,
into the hide/ or show/ folder matching its mode, where the next build picks it
up as a built-in.

    python tools/export_triggers.py [config.json]
"""
import base64
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "triggers")


def safe_name(name, index):
    cleaned = re.sub(r"[^0-9A-Za-z가-힣 _-]", "", name).strip().replace(" ", "_")
    return cleaned or f"trigger_{index}"


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    triggers = (config.get("auto_hide") or {}).get("triggers") or []
    os.makedirs(OUT_DIR, exist_ok=True)
    written = 0
    for index, trigger in enumerate(triggers, 1):
        if trigger.get("builtin") or not trigger.get("image"):
            continue
        mode = trigger.get("mode") if trigger.get("mode") in ("hide", "show") else "hide"
        folder = os.path.join(OUT_DIR, mode)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, safe_name(trigger.get("name", ""), index) + ".png")
        with open(path, "wb") as out:
            out.write(base64.b64decode(trigger["image"]))
        print("wrote", os.path.relpath(path, ROOT))
        written += 1
    if not written:
        print("no captured triggers in", config_path)


if __name__ == "__main__":
    main()
