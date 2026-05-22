import io
import os
import threading
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template, request, send_file
from anthropic import Anthropic
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

app = Flask(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

usage_history = []
latest_ratelimits = {}
session_cost_usd = 0.0
last_ping_at = None

PING_MODEL  = "claude-haiku-4-5-20251001"
PING_COST   = (1 / 1_000_000) * 0.80 + (1 / 1_000_000) * 4.00  # 1 input + 1 output token

PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00},
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def calculate_cost(model, input_tokens, output_tokens):
    price = PRICING.get(model, {"input": 3.00, "output": 15.00})
    return (input_tokens / 1_000_000) * price["input"] + \
           (output_tokens / 1_000_000) * price["output"]


def _capture_ratelimits(headers):
    global latest_ratelimits
    latest_ratelimits = {
        "requests_limit":          headers.get("anthropic-ratelimit-requests-limit"),
        "requests_remaining":      headers.get("anthropic-ratelimit-requests-remaining"),
        "requests_reset":          headers.get("anthropic-ratelimit-requests-reset"),
        "tokens_limit":            headers.get("anthropic-ratelimit-tokens-limit"),
        "tokens_remaining":        headers.get("anthropic-ratelimit-tokens-remaining"),
        "tokens_reset":            headers.get("anthropic-ratelimit-tokens-reset"),
        "input_tokens_limit":      headers.get("anthropic-ratelimit-input-tokens-limit"),
        "input_tokens_remaining":  headers.get("anthropic-ratelimit-input-tokens-remaining"),
        "output_tokens_limit":     headers.get("anthropic-ratelimit-output-tokens-limit"),
        "output_tokens_remaining": headers.get("anthropic-ratelimit-output-tokens-remaining"),
    }


def _do_ping():
    global session_cost_usd, last_ping_at
    try:
        raw = client.messages.with_raw_response.create(
            model=PING_MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "1"}],
        )
        _capture_ratelimits(raw.headers)
        parsed = raw.parsed
        cost = calculate_cost(
            PING_MODEL,
            parsed.usage.input_tokens,
            parsed.usage.output_tokens,
        )
        session_cost_usd += cost
        last_ping_at = datetime.now().strftime("%H:%M:%S")
    except Exception:
        pass


def _ping_loop():
    time.sleep(5)   # allow app to start
    while True:
        _do_ping()
        time.sleep(300)  # 5 minutes


def _get_summary():
    if not usage_history:
        return {"total_requests": 0, "total_input_tokens": 0,
                "total_output_tokens": 0, "total_cost_usd": round(session_cost_usd, 6), "avg_latency_ms": 0}
    return {
        "total_requests": len(usage_history),
        "total_input_tokens": sum(r["input_tokens"] for r in usage_history),
        "total_output_tokens": sum(r["output_tokens"] for r in usage_history),
        "total_cost_usd": round(
            sum(r["cost_usd"] for r in usage_history) + session_cost_usd, 6
        ),
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in usage_history) / len(usage_history)
        ),
    }


def render_tv_image():
    W, H = 240, 240
    BG    = (10, 10, 20)
    ACCNT = (88, 166, 255)
    WHITE = (230, 237, 243)
    DIM   = (139, 148, 158)
    GREEN = (63, 185, 80)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 15)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 12)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
    except OSError:
        font_lg = font_md = font_sm = ImageFont.load_default()

    s = _get_summary()
    draw.rectangle([0, 0, W, 26], fill=(20, 30, 48))
    draw.text((8, 6), "Claude Monitor", font=font_lg, fill=ACCNT)
    draw.text((W - 52, 8), datetime.now().strftime("%H:%M"), font=font_md, fill=DIM)
    draw.line([0, 27, W, 27], fill=(48, 54, 61), width=1)

    rows = [
        ("Requests",    str(s["total_requests"]),       WHITE),
        ("In tokens",   f"{s['total_input_tokens']:,}", DIM),
        ("Out tokens",  f"{s['total_output_tokens']:,}",DIM),
        ("Cost",        f"${s['total_cost_usd']:.5f}",  GREEN),
        ("Avg latency", f"{s['avg_latency_ms']} ms",    WHITE),
    ]
    y = 36
    for label, value, color in rows:
        draw.text((8, y), label, font=font_sm, fill=DIM)
        draw.text((W - 8 - draw.textlength(value, font=font_md), y - 1),
                  value, font=font_md, fill=color)
        y += 26

    draw.line([0, y, W, y], fill=(48, 54, 61), width=1)
    y += 6
    draw.text((8, y), "Recent", font=font_sm, fill=DIM)
    y += 14
    recent = list(reversed(usage_history[-3:]))
    if not recent:
        draw.text((8, y), "no data yet", font=font_sm, fill=DIM)
    else:
        for r in recent:
            ms = r["model"].replace("claude-", "").replace("-20251001", "")[:12]
            draw.text((8, y), f"{r['timestamp']}  {ms}", font=font_sm, fill=DIM)
            cost = f"${r['cost_usd']:.5f}"
            draw.text((W - 8 - draw.textlength(cost, font=font_sm), y),
                      cost, font=font_sm, fill=GREEN)
            y += 14

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    global session_cost_usd
    data = request.get_json()
    message = data.get("message", "").strip()
    model = data.get("model", DEFAULT_MODEL)

    if not message:
        return jsonify({"error": "message is required"}), 400

    try:
        t0 = time.time()
        raw = client.messages.with_raw_response.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": message}],
        )
        latency_ms = round((time.time() - t0) * 1000)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    response = raw.parsed
    _capture_ratelimits(raw.headers)

    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = calculate_cost(model, input_tokens, output_tokens)
    session_cost_usd += cost

    record = {
        "timestamp":    datetime.now().strftime("%H:%M:%S"),
        "model":        model,
        "input_tokens": input_tokens,
        "output_tokens":output_tokens,
        "cost_usd":     round(cost, 8),
        "latency_ms":   latency_ms,
        "preview":      message[:60] + ("…" if len(message) > 60 else ""),
    }
    usage_history.append(record)

    return jsonify({"content": response.content[0].text,
                    "usage": record, "ratelimits": latest_ratelimits})


@app.route("/api/history")
def history():
    return jsonify(list(reversed(usage_history[-100:])))


@app.route("/api/summary")
def summary():
    return jsonify(_get_summary())


@app.route("/api/ratelimits")
def ratelimits():
    return jsonify({
        **latest_ratelimits,
        "last_ping_at":    last_ping_at,
        "session_cost_usd": round(session_cost_usd, 8),
    })


@app.route("/api/tv-image")
def tv_image():
    return send_file(render_tv_image(), mimetype="image/png")


@app.route("/api/tv-push", methods=["POST"])
def tv_push():
    data = request.get_json(silent=True) or {}
    device_ip = data.get("device_ip") or os.getenv("SMALLTV_IP")
    if not device_ip:
        return jsonify({"error": "device_ip required (body JSON or SMALLTV_IP env)"}), 400
    buf = render_tv_image()
    try:
        resp = requests.post(
            f"http://{device_ip}/doUpload",
            files={"file": ("claude_monitor.png", buf, "image/png")},
            timeout=5,
        )
        return jsonify({"ok": True, "device_status": resp.status_code})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    threading.Thread(target=_ping_loop, daemon=True).start()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
