#!/usr/bin/env python3
import json
import logging
import os
import random
import sys
import time
import traceback
from copy import deepcopy
from urllib.parse import urlencode

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capcut_common_task_client import (
    BASE,
    DEFAULT_DEVICE,
    base_headers,
    build_request,
    checked_json_response,
    common_query,
    compact_json,
    load_json,
    make_sign_header,
    query_body,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("capcut-k07vn")

app = Flask(__name__)
CORS(app)

PORT = int(os.environ.get("PORT", "8081"))
VOICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Voice.json")

voices_cache = None


def load_voices():
    global voices_cache
    if voices_cache is None:
        voices_cache = load_json(str(VOICES_PATH), default=[])
    return voices_cache


def random_id():
    return str(random.randint(10**17, 10**18 - 1))


def fresh_device():
    d = deepcopy(DEFAULT_DEVICE)
    d["device_id"] = random_id()
    d["iid"] = random_id()
    d["tdid"] = d["device_id"]
    return d


def write_device_json(device):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "device.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(device, f, indent=2)
    return path


def submit_tts(texts, voice, resource_id, rate="1.0", pitch="+0%"):
    device = fresh_device()
    device_json_path = write_device_json(device)

    args = type("Args", (), {
        "mode": "tts-new",
        "text": texts,
        "text_file": None,
        "voice": voice,
        "resource_id": resource_id,
        "rate": rate,
        "pitch": pitch,
        "device_json": device_json_path,
        "task_id": None,
        "token": None,
        "bind_id": "",
    })()
    url, headers, body_text = build_request(args)

    log.info("Submitting TTS: device=%s voice=%s text=%s", device["device_id"], voice, texts)
    resp = requests.post(url, headers=headers, data=body_text.encode("utf-8"), timeout=30)
    data = checked_json_response(resp, "tts-new")
    tasks = (data.get("data") or {}).get("tasks") or []
    if not tasks:
        raise RuntimeError(f"No tasks in response: {data}")
    task = tasks[0]
    task_id = task.get("id")
    token = task.get("token")
    if not task_id or not token:
        raise RuntimeError(f"Missing task_id/token in response: {task}")
    return task_id, token, device


def poll_tts(task_id, token, device, interval=1.5, max_retries=60):
    body = query_body(task_id, token, "sami_text_to_speech", "")
    body_text = compact_json(body)
    path = "/lv/v1/common_task/query"
    query = common_query(device, None, include_region=False)
    url = BASE + path + "?" + urlencode(query)
    headers = base_headers(device, body_text, appid=True)
    lower_headers = {k.lower(): v for k, v in headers.items()}
    if "sign" not in lower_headers:
        headers["sign"] = make_sign_header(url, device["appvr"], lower_headers["device-time"], device["tdid"])

    for attempt in range(max_retries):
        resp = requests.post(url, headers=headers, data=body_text.encode("utf-8"), timeout=30)
        data = checked_json_response(resp, "tts-query")
        tasks = (data.get("data") or {}).get("tasks") or []
        if tasks:
            task = tasks[0]
            status = task.get("status")
            is_done = status == 3 or status == "succeed"
            if is_done:
                payload_str = task.get("payload") or "{}"
                try:
                    payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    payload = {}
                subtitles = payload.get("audio_subtitles") or []
                if subtitles:
                    audio_url = subtitles[0].get("speech_url")
                    if audio_url:
                        return audio_url, data
                result = task.get("result") or {}
                audio_url = result.get("audio_url") or result.get("url") or result.get("download_url")
                if audio_url:
                    return audio_url, data
                raise RuntimeError(f"Task completed but no audio_url found: {payload}")
            elif status == 4 or status == "failed":
                raise RuntimeError(f"Task failed: {task}")
        time.sleep(interval)
    raise RuntimeError(f"TTS task did not complete after {max_retries} retries")


def download_audio(audio_url, timeout=120):
    log.info("Downloading audio from %s", audio_url[:80])
    resp = requests.get(audio_url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def synthesize(text, voice, resource_id, rate="1.0", pitch="+0%"):
    task_id, token, device = submit_tts([text], voice, resource_id, rate, pitch)
    audio_url, _ = poll_tts(task_id, token, device)
    return download_audio(audio_url)


@app.route("/v1/voices", methods=["GET"])
def list_voices():
    return jsonify(load_voices())


@app.route("/v1/synthesize", methods=["POST"])
def handle_synthesize():
    try:
        body = request.get_json(silent=True) or {}
        text = body.get("text", "").strip()
        if not text:
            return jsonify({"error": "Missing 'text' field"}), 400
        voice = body.get("voice") or body.get("speaker", "BV074_streaming")
        speed = body.get("speed", 1.0)
        pitch = body.get("pitch", 0)
        resource_id = body.get("resource_id", "7102355709945188865")
        rate = str(float(speed))
        pitch_str = f"{'+' if pitch >= 0 else ''}{float(pitch) * 100:.0f}%"
        log.info("Synthesize: voice=%s text=%s pitch=%s", voice, text[:60], pitch_str)
        audio = synthesize(text, voice, resource_id, rate, pitch_str)
        return Response(audio, mimetype="audio/mpeg")
    except Exception as e:
        log.error("Synthesize error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "voices_loaded": len(load_voices())})


if __name__ == "__main__":
    log.info("Starting K07VN CapCut TTS server on port %d", PORT)
    app.run(host="127.0.0.1", port=PORT, debug=False)
