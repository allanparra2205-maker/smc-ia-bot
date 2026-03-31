"""
SMC Gold IA Server — Gemini Edition
─────────────────────────────────────
Recibe webhooks de TradingView con datos SMC del oro.
Consulta Gemini 2.5 Flash (100% gratis) para análisis.
Resultados visibles en logs de Railway en tiempo real.

Deploy gratis: Railway.app
IA gratis: aistudio.google.com
"""

import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ─── CONFIG ──────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  # aistudio.google.com → Get API Key

# ─── PROMPT SMC ──────────────────────────────────────────────
SMC_SYSTEM_PROMPT = """
Eres un analista experto en Smart Money Concepts (SMC) especializado en oro (XAUUSD).
Tu rol es evaluar si un setup detectado automáticamente es válido y de alta probabilidad.

CONCEPTOS QUE DOMINAS:
- Order Blocks (OB): zonas institucionales. OB bajista = última vela alcista antes de impulso bajista.
- BOS: confirmación de continuación rompiendo último swing high/low.
- CHoCH: primera rotura contraria a la tendencia, señal de reversión.
- FVG: imbalance entre high de vela -2 y low de vela 0 (o viceversa). El precio tiende a rellenarlo.
- Liquidity Sweep: barrido de stops para tomar liquidez antes del movimiento institucional real.
- Premium/Discount: encima del 50% del rango = premium (ideal sells). Debajo = discount (ideal buys).
- Confluencia HTF/LTF: sesgo H4/H1 debe alinearse con entrada M15/M5.

CRITERIOS DE PUNTUACIÓN (1-10):
+2 OB fresco (no testeado antes)
+2 CHoCH confirmado
+2 Liquidity sweep previo
+1 FVG presente en zona entrada
+1 Sesión Londres o Nueva York
+1 Precio en premium (sell) o discount (buy)
+1 Alineación con sesgo HTF

RESTAR PUNTOS O IGNORAR SI:
- OB ya testeado múltiples veces
- Solo BOS sin CHoCH
- Sesión asiática (bajo volumen en oro)
- Sin FVG ni liquidity sweep
- ATR muy bajo (mercado sin momentum)

RESPONDE SOLO EN ESTE JSON EXACTO (sin markdown, sin texto extra):
{
  "decision": "EJECUTAR" | "ESPERAR" | "IGNORAR",
  "puntuacion": 1-10,
  "confianza": "ALTA" | "MEDIA" | "BAJA",
  "analisis": "2-3 oraciones técnicas explicando el setup",
  "confluencias": ["factores SMC presentes"],
  "sl_ajustado": numero,
  "tp1": numero,
  "tp2": numero,
  "zona_precio": "PREMIUM" | "DISCOUNT" | "EQUILIBRIO",
  "advertencias": "riesgos o condiciones a vigilar"
}
"""

# ─── FUNCIONES ───────────────────────────────────────────────

def get_session(hour_utc: int) -> str:
    if 7 <= hour_utc < 12:
        return "Londres"
    elif 12 <= hour_utc < 16:
        return "Overlap Londres-NY"
    elif 16 <= hour_utc < 21:
        return "Nueva York"
    else:
        return "Asia / Fuera de sesión"

def build_prompt(data: dict) -> str:
    tipo      = data.get("tipo", "?")
    precio    = data.get("precio", 0)
    sl        = data.get("sl", 0)
    atr       = data.get("atr", 1)
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
    if bos:   cf.append("BOS confirmado")
    if choch: cf.append("CHoCH detectado")
    if fvg:   cf.append("Fair Value Gap")
    if liq:   cf.append("Liquidity Sweep previo")

    return f"""
SETUP XAUUSD — {tipo} | Timeframe: M{tf}
Sesión: {sesion} (UTC {hora_utc}:00)

ESTRUCTURA:
- Tendencia: {tendencia}
- BOS: {"✓" if bos else "✗"} | CHoCH: {"✓" if choch else "✗"}
- FVG: {"✓" if fvg else "✗"} | Liq. Sweep: {"✓" if liq else "✗"}
- Confluencias activas ({len(cf)}): {', '.join(cf) if cf else "ninguna"}

ORDER BLOCK:
- OB High: {ob_hi} | OB Low: {ob_lo}
- Precio actual: {precio}
- Dentro del OB: {"✓ Sí" if ob_lo <= precio <= ob_hi else "✗ No"}
- Zona: {zona}

RIESGO:
- SL técnico: {sl} ({sl_dist:.2f} pts = {sl_dist/atr:.1f}x ATR)
- ATR(14): {atr:.2f}
- TP 2:1 → {rr2:.2f} | TP 3:1 → {rr3:.2f}

Evalúa y responde en JSON.
"""

def analyze(data: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "system_instruction": {"parts": [{"text": SMC_SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": build_prompt(data)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 600,
            "responseMimeType": "application/json"
        }
    }

    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()

    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    raw = raw.replace("```json", "").replace("```", "").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()

    return json.loads(raw)
    

def print_result(data: dict, result: dict):
    """Log visual claro en Railway."""
    tipo      = data.get("tipo", "?")
    precio    = data.get("precio", 0)
    decision  = result.get("decision", "?")
    puntuacion = result.get("puntuacion", 0)
    confianza = result.get("confianza", "?")
    analisis  = result.get("analisis", "")
    cf        = result.get("confluencias", [])
    sl        = result.get("sl_ajustado", 0)
    tp1       = result.get("tp1", 0)
    tp2       = result.get("tp2", 0)
    zona      = result.get("zona_precio", "?")
    adv       = result.get("advertencias", "")

    emoji = "🔴" if tipo == "SELL" else "🟢"
    dec_e = "✅" if decision == "EJECUTAR" else "⏳" if decision == "ESPERAR" else "❌"

    print(f"""
{'='*50}
{emoji}  SMC GOLD — {tipo} @ {precio}
{'='*50}
{dec_e}  DECISIÓN: {decision}
⭐  Puntuación: {puntuacion}/10  |  Confianza: {confianza}
📊  Zona: {zona}

💬 {analisis}

🔗 Confluencias:
{chr(10).join(f"   • {c}" for c in cf) if cf else "   • Ninguna"}

💰 Gestión:
   SL → {sl}
   TP1 → {tp1}  |  TP2 → {tp2}

⚠️  {adv}
{'='*50}
""")

# ─── RUTAS ───────────────────────────────────────────────────

@app.route("/signal", methods=["POST"])
def receive_signal():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400

    print(f"\n📨 Señal recibida: {data.get('tipo','?')} @ {data.get('precio','?')}")

    try:
        print("🤖 Analizando con Gemini...")
        result = analyze(data)
        print_result(data, result)

        return jsonify({
            "status":     "ok",
            "decision":   result.get("decision"),
            "puntuacion": result.get("puntuacion"),
            "confianza":  result.get("confianza"),
            "zona":       result.get("zona_precio")
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
    """Prueba completa sin necesitar TradingView."""
    test_data = {
        "tipo":      "SELL",
        "simbolo":   "XAUUSD",
        "precio":    3020.50,
        "sl":        3028.00,
        "atr":       4.20,
        "tendencia": -1,
        "timeframe": "5",
        "bos":       True,
        "choch":     True,
        "fvg":       True,
        "liq_sweep": True,
        "ob_hi":     3025.00,
        "ob_lo":     3021.50,
        "timestamp": datetime.utcnow().isoformat()
    }
    result = analyze(test_data)
    print_result(test_data, result)
    return jsonify({"test": "ok", "resultado": result})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SMC Gold IA Server")
    print(f"   Gemini: {'✅ listo' if GEMINI_API_KEY else '❌ FALTA GEMINI_API_KEY'}")
    print(f"   Puerto: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
