import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SMC_PROMPT = """Eres un analista SMC de oro (XAUUSD). Evalua el setup y responde UNICAMENTE con este JSON sin texto adicional:
{"decision":"EJECUTAR","puntuacion":8,"confianza":"ALTA","analisis":"texto corto","confluencias":["factor1"],"sl_ajustado":3028.0,"tp1":3010.0,"tp2":3005.0,"zona_precio":"PREMIUM","advertencias":"texto"}"""

def analyze(data: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    tipo  = data.get("tipo", "?")
    precio= data.get("precio", 0)
    sl    = data.get("sl", 0)
    atr   = data.get("atr", 1)
    bos   = data.get("bos", False)
    choch = data.get("choch", False)
    fvg   = data.get("fvg", False)
    liq   = data.get("liq_sweep", False)
    ob_hi = data.get("ob_hi", 0)
    ob_lo = data.get("ob_lo", 0)
    tf    = data.get("timeframe", "?")
    hora  = datetime.utcnow().hour
    tendencia = "BAJISTA" if data.get("tendencia", 0) == -1 else "ALCISTA"

    prompt = f"SETUP: {tipo} XAUUSD M{tf}. Precio:{precio} SL:{sl} ATR:{atr} Tendencia:{tendencia} BOS:{bos} CHoCH:{choch} FVG:{fvg} LiqSweep:{liq} OB:{ob_lo}-{ob_hi} HoraUTC:{hora}. Responde SOLO el JSON."

    payload = {
        "system_instruction": {"parts": [{"text": SMC_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512}
    }

    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()

    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    raw = raw.strip().replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"Sin JSON: {raw[:100]}")
    return json.loads(raw[start:end])

@app.route("/test", methods=["GET"])
def test():
    data = {
        "tipo": "SELL", "precio": 3020.50, "sl": 3028.00,
        "atr": 4.20, "tendencia": -1, "timeframe": "5",
        "bos": True, "choch": True, "fvg": True, "liq_sweep": True,
        "ob_hi": 3025.00, "ob_lo": 3021.50
    }
    result = analyze(data)
    print(f"RESULTADO: {result}")
    return jsonify({"test": "ok", "resultado": result})

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "Sin datos"}), 400
    try:
        result = analyze(data)
        print(f"SENAL {data.get('tipo')} @ {data.get('precio')} -> {result.get('decision')} {result.get('puntuacion')}/10")
        return jsonify({"status": "ok", "decision": result.get("decision"), "puntuacion": result.get("puntuacion"), "confianza": result.get("confianza"), "resultado": result})
    except Exception as e:
        print(f"ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "modelo": "gemini-2.0-flash", "gemini": bool(GEMINI_API_KEY)})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "SMC IA corriendo"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
