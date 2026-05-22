import io
import os
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


def _get_summary():
    if not usage_history:
        return {"total_requests": 0, "total_input_tokens": 0,
                "total_output_tokens": 0, "total_cost_usd": 0, "avg_latency_ms": 0}
    return {
        "total_requests": len(usage_history),
        "total_input_tokens": sum(r["input_tokens"] for r in usage_history),
        "total_output_tokens": sum(r["output_tokens"] for r in usage_history),
        "total_cost_usd": round(sum(r["cost_usd"] for r in usage_history), 6),
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in usage_history) / len(usage_history)
        ),
    }


def render_tv_image():
    """Render a 240x240 PNG showing usage stats for SmallTV Ultra."""
    W, H = 240, 240
    BG      = (10, 10, 20)
    ACCENT  = (88, 166, 255)
    WHITE   = (230, 237, 243)
    DIM     = (139, 148, 158)
    GREEN   = (63, 185, 80)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 15)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 12)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
    except OSError:
        font_lg = font_md = font_sm = ImageFont.load_default()

    s = _get_summary()

    # header
    draw.rectangle([0, 0, W, 26], fill=(20, 30, 48))
    draw.text((8, 6), "Claude Monitor", font=font_lg, fill=ACCENT)
    draw.text((W - 52, 8), datetime.now().strftime("%H:%M"), font=font_md, fill=DIM)

    # divider
    draw.line([0, 27, W, 27], fill=(48, 54, 61), width=1)

    # stats rows
    rows = [
        ("Requests",    str(s["total_requests"]),                    WHITE),
        ("In tokens",   f"{s['total_input_tokens']:,}",              DIM),
        ("Out tokens",  f"{s['total_output_tokens']:,}",             DIM),
        ("Total cost",  f"${s['total_cost_usd']:.5f}",               GREEN),
        ("Avg latency", f"{s['avg_latency_ms']} ms",                 WHITE),
    ]

    y = 36
    for label, value, color in rows:
        draw.text((8, y), label, font=font_sm, fill=DIM)
        draw.text((W - 8 - draw.textlength(value, font=font_md), y - 1), value, font=font_md, fill=color)
        y += 26

    # divider before history
    draw.line([0, y, W, y], fill=(48, 54, 61), width=1)
    y += 6

    # last 3 requests
    draw.text((8, y), "Recent", font=font_sm, fill=DIM)
    y += 14

    recent = list(reversed(usage_history[-3:]))
    if not recent:
        draw.text((8, y), "no data yet", font=font_sm, fill=DIM)
    else:
        for r in recent:
            model_short = r["model"].replace("claude-", "").replace("-20251001", "")[:12]
            line = f"{r['timestamp']}  {model_short}"
            cost = f"${r['cost_usd']:.5f}"
            draw.text((8, y), line, font=font_sm, fill=DIM)
            draw.text((W - 8 - draw.textlength(cost, font=font_sm), y), cost, font=font_sm, fill=GREEN)
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
    h = raw.headers
    latest_ratelimits.update({
        "requests_limit":          h.get("anthropic-ratelimit-requests-limit"),
        "requests_remaining":      h.get("anthropic-ratelimit-requests-remaining"),
        "requests_reset":          h.get("anthropic-ratelimit-requests-reset"),
        "tokens_limit":            h.get("anthropic-ratelimit-tokens-limit"),
        "tokens_remaining":        h.get("anthropic-ratelimit-tokens-remaining"),
        "tokens_reset":            h.get("anthropic-ratelimit-tokens-reset"),
        "input_tokens_limit":      h.get("anthropic-ratelimit-input-tokens-limit"),
        "input_tokens_remaining":  h.get("anthropic-ratelimit-input-tokens-remaining"),
        "output_tokens_limit":     h.get("anthropic-ratelimit-output-tokens-limit"),
        "output_tokens_remaining": h.get("anthropic-ratelimit-output-tokens-remaining"),
    })

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = calculate_cost(model, input_tokens, output_tokens)

    record = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 8),
        "latency_ms": latency_ms,
        "preview": message[:60] + ("…" if len(message) > 60 else ""),
    }
    usage_history.append(record)

    return jsonify({"content": response.content[0].text, "usage": record, "ratelimits": latest_ratelimits})


@app.route("/api/history")
def history():
    return jsonify(list(reversed(usage_history[-100:])))


@app.route("/api/summary")
def summary():
    return jsonify(_get_summary())


@app.route("/api/ratelimits")
def ratelimits():
    return jsonify(latest_ratelimits)


@app.route("/api/tv-image")
def tv_image():
    """Return a 240x240 PNG preview of the SmallTV panel."""
    buf = render_tv_image()
    return send_file(buf, mimetype="image/png")


@app.route("/api/tv-push", methods=["POST"])
def tv_push():
    """Render usage stats as PNG and push to SmallTV Ultra via /doUpload."""
    data = request.get_json(silent=True) or {}
    device_ip = data.get("device_ip") or os.getenv("SMALLTV_IP")

    if not device_ip:
        return jsonify({"error": "device_ip required (body JSON or SMALLTV_IP env)"}), 400

    buf = render_tv_image()
    upload_url = f"http://{device_ip}/doUpload"

    try:
        resp = requests.post(
            upload_url,
            files={"file": ("claude_monitor.png", buf, "image/png")},
            timeout=5,
        )
        return jsonify({"ok": True, "device_status": resp.status_code})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
