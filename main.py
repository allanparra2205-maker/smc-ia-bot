from flask import Flask, request, jsonify
import requests
import os
import numpy as np
from sklearn.preprocessing import StandardScaler
import json
from datetime import datetime

app = Flask(__name__)

# ═══════════════════════════════════════════
# CONFIGURACION — pon tus datos aqui
# ═══════════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ═══════════════════════════════════════════
# MODELO IA — KNN simple entrenado con logica SMC
# ═══════════════════════════════════════════
# Features: [rr, trend_score, liquidity_hit, ob_quality, fvg_present]
# Labels: 1 = buena entrada, 0 = entrada debil

training_data = np.array([
    [2.0, 1.0, 1.0, 1.0, 1.0],
    [2.0, 1.0, 1.0, 0.8, 1.0],
    [1.5, 1.0, 1.0, 1.0, 0.5],
    [2.5, 1.0, 1.0, 1.0, 1.0],
    [2.0, 0.8, 1.0, 0.8, 1.0],
    [1.0, 0.5, 0.5, 0.5, 0.0],
    [1.0, 0.3, 1.0, 0.3, 0.0],
    [2.0, 0.2, 0.5, 0.5, 0.5],
    [1.5, 0.0, 1.0, 0.3, 0.0],
    [1.0, 0.1, 0.5, 0.2, 0.0],
])
training_labels = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])

scaler = StandardScaler()
X_train = scaler.fit_transform(training_data)

def knn_predict(features, k=3):
    x = scaler.transform([features])
    distances = np.sqrt(np.sum((X_train - x) ** 2, axis=1))
    k_indices = np.argsort(distances)[:k]
    k_labels = training_labels[k_indices]
    confidence = np.sum(k_labels) / k
    prediction = 1 if confidence >= 0.5 else 0
    return prediction, round(confidence * 100)

# ═══════════════════════════════════════════
# ENVIAR MENSAJE A TELEGRAM
# ═══════════════════════════════════════════
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram no configurado")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

# ═══════════════════════════════════════════
# WEBHOOK — recibe alertas de TradingView
# ═══════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "sin datos"}), 400

        signal    = data.get("signal", "").upper()      # BUY o SELL
        ticker    = data.get("ticker", "UNKNOWN")
        timeframe = data.get("timeframe", "?")
        rr        = float(data.get("rr", 2.0))
        trend     = float(data.get("trend", 1.0))       # 1=favor, 0=contra
        liq_hit   = float(data.get("liq_hit", 1.0))     # 1=toco liquidez
        ob_q      = float(data.get("ob_quality", 0.8))  # calidad OB 0-1
        fvg       = float(data.get("fvg", 1.0))         # 1=hay FVG

        # IA evalua la señal
        features = [rr, trend, liq_hit, ob_q, fvg]
        prediction, confidence = knn_predict(features)

        now = datetime.now().strftime("%d/%m %H:%M")

        if prediction == 1:
            emoji = "🟢" if signal == "BUY" else "🔴"
            msg = (
                f"{emoji} <b>SEÑAL SMC — {signal}</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📊 Par: <b>{ticker}</b>\n"
                f"⏱ Temporalidad: {timeframe}\n"
                f"🤖 Confianza IA: <b>{confidence}%</b>\n"
                f"📐 R/R: {rr}\n"
                f"🕐 {now}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"✅ <i>Confluencia SMC confirmada</i>"
            )
        else:
            msg = (
                f"⚠️ <b>SEÑAL DÉBIL — {signal} {ticker}</b>\n"
                f"🤖 Confianza IA: {confidence}%\n"
                f"❌ <i>IA recomienda no entrar</i>\n"
                f"🕐 {now}"
            )

        send_telegram(msg)
        return jsonify({"status": "ok", "signal": signal, "confidence": confidence}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════
# PING — mantiene el servidor despierto
# ═══════════════════════════════════════════
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive"}), 200

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "SMC IA Bot corriendo"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
