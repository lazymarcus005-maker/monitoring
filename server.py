import os
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

usage_history = []

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
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": message}],
        )
        latency_ms = round((time.time() - t0) * 1000)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

    return jsonify({"content": response.content[0].text, "usage": record})


@app.route("/api/history")
def history():
    return jsonify(list(reversed(usage_history[-100:])))


@app.route("/api/summary")
def summary():
    if not usage_history:
        return jsonify({
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0,
            "avg_latency_ms": 0,
        })
    return jsonify({
        "total_requests": len(usage_history),
        "total_input_tokens": sum(r["input_tokens"] for r in usage_history),
        "total_output_tokens": sum(r["output_tokens"] for r in usage_history),
        "total_cost_usd": round(sum(r["cost_usd"] for r in usage_history), 6),
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in usage_history) / len(usage_history)
        ),
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=True, port=port)
