#!/usr/bin/env python3
"""Throwaway spike: can GitHub Actions reach the CapCut TTS API?

Starts the local Flask proxy (server.py) and hits /v1/synthesize with a few
Vietnamese sentences of increasing length. Reports HTTP status, byte size and
latency so we can judge (a) IP/geo blocking and (b) the per-request length cap
from a cloud runner.
"""
import json
import os
import subprocess
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8081
BASE = f"http://127.0.0.1:{PORT}"
VOICE = "multi_female_richgirl_uranus_bigtts"
RESID = "7637460351541447956"

TESTS = [
    ("short", "Xin chào, đây là bài kiểm tra giọng đọc."),
    ("~120", "Trong thế giới của những trò chơi điện tử, có một câu chuyện bí ẩn "
             "mà ít ai từng nghe kể, và hôm nay chúng ta sẽ cùng nhau khám phá nó."),
    ("~250", "Trong thế giới của những trò chơi điện tử, có một câu chuyện bí ẩn mà ít ai từng "
             "nghe kể, và hôm nay chúng ta sẽ cùng nhau khám phá nó. Nhân vật chính bước vào "
             "một căn phòng tối, nơi ánh đèn nhấp nháy phản chiếu trên màn hình máy tính cũ kỹ. "
             "Không ai biết điều gì đang chờ đợi phía sau cánh cửa đó."),
    ("~420", "Trong thế giới của những trò chơi điện tử, có một câu chuyện bí ẩn mà ít ai từng "
             "nghe kể, và hôm nay chúng ta sẽ cùng nhau khám phá nó. Nhân vật chính bước vào "
             "một căn phòng tối, nơi ánh đèn nhấp nháy phản chiếu trên màn hình máy tính cũ kỹ. "
             "Không ai biết điều gì đang chờ đợi phía sau cánh cửa đó. Anh ta nghe thấy một âm "
             "thanh kỳ lạ phát ra từ chiếc loa cũ, giống như một giọng nói đang thì thầm tên mình. "
             "Đó chỉ là khởi đầu của mọi chuyện."),
]


def wait_health(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{BASE}/health", timeout=5)
            if r.status_code == 200:
                return r.json(), time.time() - t0
        except Exception:
            pass
        time.sleep(2)
    return None, time.time() - t0


def main():
    proc = subprocess.Popen(
        [sys.executable, "-u", os.path.join(HERE, "server.py")],
        cwd=HERE,
        stdout=open(os.path.join(HERE, "server.log"), "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    result = {"runner": os.environ.get("RUNNER_NAME"), "health": None}
    try:
        health, wait = wait_health()
        result["health"] = health
        result["health_wait_s"] = round(wait, 1)
        print("HEALTH:", health, "after", round(wait, 1), "s", flush=True)

        result["tests"] = []
        for label, text in TESTS:
            t0 = time.time()
            try:
                r = requests.post(
                    f"{BASE}/v1/synthesize",
                    json={"text": text, "voice": VOICE, "resource_id": RESID},
                    timeout=180,
                )
                dt = time.time() - t0
                size = len(r.content)
                ok = r.status_code == 200 and size > 2000
                entry = {"label": label, "chars": len(text), "status": r.status_code,
                         "bytes": size, "seconds": round(dt, 1), "ok": ok}
                if not ok:
                    entry["body"] = r.text[:200]
                result["tests"].append(entry)
                print("TEST:", json.dumps(entry, ensure_ascii=False), flush=True)
            except Exception as e:
                result["tests"].append({"label": label, "chars": len(text),
                                        "error": str(e)[:200]})
                print("TEST ERROR:", label, str(e)[:200], flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    with open(os.path.join(HERE, "probe_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("RESULT:", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
