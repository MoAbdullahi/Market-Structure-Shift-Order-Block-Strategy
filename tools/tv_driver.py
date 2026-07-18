"""CDP driver for the TradingView desktop app (Electron, --remote-debugging-port=9222).

Gives screenshot / click / type / key / eval / scroll control over the chart tab,
so the strategy replay study can be driven programmatically.

Usage:
  python tools/tv_driver.py shot [--out PATH]
  python tools/tv_driver.py click X Y [--double] [--right]
  python tools/tv_driver.py move X Y
  python tools/tv_driver.py drag X1 Y1 X2 Y2
  python tools/tv_driver.py type "text"
  python tools/tv_driver.py key KEY        (Enter, Escape, ArrowRight, F7 ... [--repeat N])
  python tools/tv_driver.py scroll X Y DY
  python tools/tv_driver.py eval "js expression"
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import sys
import time
import urllib.request

import websocket

DEBUG_HTTP = "http://localhost:9222"
_id_counter = itertools.count(1)

KEY_DEFS = {
    # key: (windowsVirtualKeyCode, code, text)
    "Enter": (13, "Enter", "\r"),
    "Escape": (27, "Escape", ""),
    "Tab": (9, "Tab", "\t"),
    "Backspace": (8, "Backspace", ""),
    "Delete": (46, "Delete", ""),
    "ArrowRight": (39, "ArrowRight", ""),
    "ArrowLeft": (37, "ArrowLeft", ""),
    "ArrowUp": (38, "ArrowUp", ""),
    "ArrowDown": (40, "ArrowDown", ""),
    "Space": (32, "Space", " "),
    "Home": (36, "Home", ""),
    "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""),
    "PageDown": (34, "PageDown", ""),
    "F7": (118, "F7", ""),
}


def chart_ws_url() -> str:
    with urllib.request.urlopen(f"{DEBUG_HTTP}/json/list", timeout=5) as r:
        targets = json.load(r)
    for t in targets:
        if t.get("type") == "page" and "tradingview.com/chart" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    raise SystemExit("chart tab not found — is the app running with the debug port?")


def connect() -> websocket.WebSocket:
    ws = websocket.create_connection(chart_ws_url(), timeout=30, suppress_origin=True)
    return ws


def send(ws: websocket.WebSocket, method: str, params: dict | None = None) -> dict:
    msg_id = next(_id_counter)
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            if "error" in resp:
                raise RuntimeError(f"{method}: {resp['error']}")
            return resp.get("result", {})


def mouse(ws, mtype, x, y, button="none", clicks=0, delta_y=0):
    params = {
        "type": mtype,
        "x": float(x),
        "y": float(y),
        "button": button,
        "clickCount": clicks,
    }
    if mtype == "mouseWheel":
        params["deltaX"] = 0
        params["deltaY"] = float(delta_y)
    send(ws, "Input.dispatchMouseEvent", params)


def do_click(ws, x, y, button="left", double=False):
    mouse(ws, "mouseMoved", x, y)
    time.sleep(0.05)
    n = 2 if double else 1
    for c in range(1, n + 1):
        mouse(ws, "mousePressed", x, y, button, c)
        time.sleep(0.03)
        mouse(ws, "mouseReleased", x, y, button, c)
        time.sleep(0.05)


def _char_key_def(ch: str):
    if ch.isdigit():
        return (ord(ch), f"Digit{ch}", ch)
    if ch.isalpha() and len(ch) == 1:
        return (ord(ch.upper()), f"Key{ch.upper()}", ch)
    if ch == ",":
        return (188, "Comma", ",")
    if ch == "-":
        return (189, "Minus", "-")
    if ch == ".":
        return (190, "Period", ".")
    if ch == "/":
        return (191, "Slash", "/")
    if ch == ":":
        return (186, "Semicolon", ":")
    return None


def do_key(ws, key: str, repeat: int = 1):
    kd = KEY_DEFS.get(key) or _char_key_def(key)
    if kd is None:
        raise SystemExit(f"unknown key {key!r}; add it to KEY_DEFS")
    vk, code, text = kd
    key_name = text if text and len(key) == 1 else key
    for _ in range(repeat):
        down = {
            "type": "keyDown",
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
            "code": code,
            "key": key_name,
        }
        if text:
            down["text"] = text
            down["unmodifiedText"] = text
        send(ws, "Input.dispatchKeyEvent", down)
        up = {
            "type": "keyUp",
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
            "code": code,
            "key": key_name,
        }
        send(ws, "Input.dispatchKeyEvent", up)
        time.sleep(0.04)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("shot")
    p.add_argument("--out", default=None)

    p = sub.add_parser("click")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)
    p.add_argument("--double", action="store_true")
    p.add_argument("--right", action="store_true")

    p = sub.add_parser("move")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)

    p = sub.add_parser("drag")
    p.add_argument("x1", type=float)
    p.add_argument("y1", type=float)
    p.add_argument("x2", type=float)
    p.add_argument("y2", type=float)

    p = sub.add_parser("type")
    p.add_argument("text")

    p = sub.add_parser("key")
    p.add_argument("key")
    p.add_argument("--repeat", type=int, default=1)

    p = sub.add_parser("scroll")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)
    p.add_argument("dy", type=float)

    p = sub.add_parser("eval")
    p.add_argument("js")

    args = ap.parse_args()
    ws = connect()
    # Screenshots are captured at devicePixelRatio scale; Input events use CSS px.
    # All mouse coordinates given to this tool are SCREENSHOT pixels — scale them.
    dpr = 1.0
    if args.cmd in ("click", "move", "drag", "scroll"):
        res = send(
            ws,
            "Runtime.evaluate",
            {"expression": "window.devicePixelRatio", "returnByValue": True},
        )
        dpr = float(res.get("result", {}).get("value") or 1.0)
        for attr in ("x", "y", "x1", "y1", "x2", "y2"):
            if hasattr(args, attr):
                setattr(args, attr, getattr(args, attr) / dpr)
    try:
        if args.cmd == "shot":
            res = send(ws, "Page.captureScreenshot", {"format": "jpeg", "quality": 70})
            out = args.out or "tv_shot.jpg"
            with open(out, "wb") as f:
                f.write(base64.b64decode(res["data"]))
            print(out)
        elif args.cmd == "click":
            do_click(ws, args.x, args.y, "right" if args.right else "left", args.double)
            print("clicked")
        elif args.cmd == "move":
            mouse(ws, "mouseMoved", args.x, args.y)
            print("moved")
        elif args.cmd == "drag":
            mouse(ws, "mouseMoved", args.x1, args.y1)
            time.sleep(0.05)
            mouse(ws, "mousePressed", args.x1, args.y1, "left", 1)
            steps = 12
            for i in range(1, steps + 1):
                xi = args.x1 + (args.x2 - args.x1) * i / steps
                yi = args.y1 + (args.y2 - args.y1) * i / steps
                mouse(ws, "mouseMoved", xi, yi, "left")
                time.sleep(0.02)
            mouse(ws, "mouseReleased", args.x2, args.y2, "left", 1)
            print("dragged")
        elif args.cmd == "type":
            send(ws, "Input.insertText", {"text": args.text})
            print("typed")
        elif args.cmd == "key":
            do_key(ws, args.key, args.repeat)
            print("key sent")
        elif args.cmd == "scroll":
            mouse(ws, "mouseWheel", args.x, args.y, delta_y=args.dy)
            print("scrolled")
        elif args.cmd == "eval":
            res = send(
                ws,
                "Runtime.evaluate",
                {"expression": args.js, "returnByValue": True, "awaitPromise": True},
            )
            print(json.dumps(res.get("result", {}).get("value"), default=str))
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
