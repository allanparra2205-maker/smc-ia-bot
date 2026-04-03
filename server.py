"""
SMC Gold IA Server — Gemini 2.5 Flash + CORS
"""
import os
import json
import re
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SMC_SYSTEM_PROMPT = """
Eres un analista experto en Smart Money Concepts (SMC) especializado en oro (XAUUSD).
Evalúa si un setup es válido y de alta probabilidad.

CONCEPTOS:
- Order Blocks (OB): zonas institucionales de oferta/demanda.
- BOS: confirmación de tendencia rompiendo swing high/low.
- CHoCH: primera rotura contraria, señal de reversión.
- FVG: imbalance de precio que el mercado tiende a rellenar.
- Liquidity Sweep: barrido de stops antes del movimiento real.
- Premium/Discount: encima 50% = premium (sells). Debajo = discount (buys).

PUNTUACIÓN (1-10):
+2 OB fresco no testeado
+2 CHoCH confirmado
+2 Liquidity Sweep previo
+1 FVG presente
+1 Sesión Londres o Nueva York
+1 Precio en zona correcta (premium/discount)
+1 Alineación con sesgo HTF

RESPONDE SOLO CON ESTE JSON EXACTO sin texto adicional:
{"decision":"EJECUTAR","puntuacion":8,"confianza":"ALTA","analisis":"texto del analisis aqui","confluencias":["factor1","factor2"],"sl_ajustado":0.0,"tp1":0.0,"tp2":0.0,"zona_precio":"PREMIUM","advertencias":"texto advertencias"}
"""

def get_session(hour_utc):
    if 7 <= hour_utc < 12:    return "Londres"
    elif 12 <= hour_utc < 16: return "Overlap Londres-NY"
    elif 16 <= hour_utc < 21: return "Nueva York"
    else:                     return "Asia"

def build_prompt(data):
    tipo      = data.get("tipo", "?")
    precio    = data.get("precio", 0)
    sl        = data.get("sl", 0)
    atr       = data.get("atr", 1) or 1
    tendencia = "BAJISTA" if data.get("tendencia", 0) == -1 else "ALCISTA"
    tf        = data.get("timeframe", "?")
    bos       = data.get("bos", False)
    choch     = data.get("choch", False)
    fvg       = data.get("fvg", False)
    liq       = data.get("liq_sweep", False)
    ob_hi     = data.get("ob_hi", 0)
    ob_lo     = data.get("ob_lo", 0)

    hora_utc  = datetime.utcnow().hour
    sesion    = get_session(hora_utc)
    sl_dist   = abs(precio - sl)
    rr2       = precio - sl_dist * 2 if tipo == "SELL" else precio + sl_dist * 2
    rr3       = precio - sl_dist * 3 if tipo == "SELL" else precio + sl_dist * 3
    ob_mid    = (ob_hi + ob_lo) / 2 if ob_hi and ob_lo else precio
    zona      = "PREMIUM" if precio > ob_mid else "DISCOUNT"

    cf = []
    if bos:   cf.append("BOS")
    if choch: cf.append("CHoCH")
    if fvg:   cf.append("FVG")
    if liq:   cf.append("Liquidity Sweep")

    return f"""SETUP: {tipo} XAUUSD | TF: M{tf} | Sesion: {sesion}
Tendencia: {tendencia} | Zona: {zona}
BOS:{bos} CHoCH:{choch} FVG:{fvg} LiqSweep:{liq}
Confluencias({len(cf)}): {', '.join(cf) if cf else 'ninguna'}
OB: {ob_lo} - {ob_hi} | Precio: {precio} | ATR: {atr:.2f}
SL: {sl} ({sl_dist:.2f}pts) | TP2:1={rr2:.2f} | TP3:1={rr3:.2f}
Responde SOLO con el JSON."""

def extract_json(text):
    matches = re.findall(r'\{[^{}]*"decision"[^{}]*\}', text, re.DOTALL)
    if matches:
        for m in reversed(matches):
            try:
                return json.loads(m)
            except:
                continue
    start = text.find('{')
    end   = text.rfind('}') + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except:
            pass
    raise ValueError(f"No JSON encontrado en: {text[:300]}")

def analyze(data):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": SMC_SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": build_prompt(data)}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1000}
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    full_text = "".join(p.get("text", "") for p in parts)
    print(f"📝 Gemini: {full_text[:400]}")
    return extract_json(full_text)

def print_result(data, result):
    tipo = data.get("tipo", "?")
    precio = data.get("precio", 0)
    dec = result.get("decision", "?")
    emoji = "🔴" if tipo == "SELL" else "🟢"
    dec_e = "✅" if dec == "EJECUTAR" else "⏳" if dec == "ESPERAR" else "❌"
    print(f"""
{'='*50}
{emoji} SMC GOLD — {tipo} @ {precio}
{dec_e} DECISIÓN: {dec} | {result.get('puntuacion',0)}/10 | {result.get('confianza','?')}
📊 Zona: {result.get('zona_precio','?')}
💬 {result.get('analisis','')}
🔗 {', '.join(result.get('confluencias',[]))}
💰 SL={result.get('sl_ajustado',0)} TP1={result.get('tp1',0)} TP2={result.get('tp2',0)}
⚠️  {result.get('advertencias','')}
{'='*50}
""")

@app.route("/signal", methods=["POST"])
def receive_signal():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400
    print(f"\n📨 Señal: {data.get('tipo','?')} @ {data.get('precio','?')}")
    try:
        result = analyze(data)
        print_result(data, result)
        return jsonify({
            "status":      "ok",
            "decision":    result.get("decision"),
            "puntuacion":  result.get("puntuacion"),
            "confianza":   result.get("confianza"),
            "analisis":    result.get("analisis"),
            "confluencias": result.get("confluencias"),
            "sl_ajustado": result.get("sl_ajustado"),
            "tp1":         result.get("tp1"),
            "tp2":         result.get("tp2"),
            "zona_precio": result.get("zona_precio"),
            "advertencias": result.get("advertencias")
        })
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":   "✅ corriendo",
        "modelo":   "gemini-2.5-flash (gratis)",
        "gemini":   "configurado" if GEMINI_API_KEY else "❌ FALTA GEMINI_API_KEY",
        "hora_utc": datetime.utcnow().strftime("%H:%M:%S")
    })

@app.route("/test", methods=["GET"])
def test():
    test_data = {
        "tipo": "SELL", "simbolo": "XAUUSD", "precio": 3020.50,
        "sl": 3028.00, "atr": 4.20, "tendencia": -1, "timeframe": "5",
        "bos": True, "choch": True, "fvg": True, "liq_sweep": True,
        "ob_hi": 3025.00, "ob_lo": 3021.50,
        "timestamp": datetime.utcnow().isoformat()
    }
    result = analyze(test_data)
    print_result(test_data, result)
    return jsonify({"test": "ok", "resultado": result})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SMC Gold IA | Gemini: {'✅' if GEMINI_API_KEY else '❌'} | Puerto: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
