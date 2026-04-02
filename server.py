import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SMC_SYSTEM_PROMPT = """Eres un analista experto en Smart Money Concepts (SMC) especializado en oro (XAUUSD).
Evalua el setup y responde UNICAMENTE con JSON valido, sin markdown, sin texto extra.

CONCEPTOS SMC:
- Order Block (OB): zona institucional. OB bajista = ultima vela alcista antes de impulso bajista. OB alcista = ultima vela bajista antes de impulso alcista.
- BOS (Break of Structure): confirmacion de continuacion rompiendo ultimo swing high/low.
- CHoCH (Change of Character): primera rotura contraria a tendencia, senal de reversion.
- FVG (Fair Value Gap): imbalance entre velas. El precio tiende a rellenarlo.
- Liquidity Sweep: barrido de stops para tomar liquidez antes del movimiento institucional real.
- Premium/Discount: encima del 50% del rango = premium (ideal sells). Debajo = discount (ideal buys).
- Sesion: Londres (7-12 UTC) y Nueva York (12-21 UTC) son las mas importantes para oro.

CRITERIOS DE PUNTUACION (1-10):
+2 OB fresco no testeado
+2 CHoCH confirmado
+2 Liquidity Sweep previo
+1 FVG en zona de entrada
+1 Sesion Londres o Nueva York
+1 Precio en premium (sell) o discount (buy)
+1 Alineacion con sesgo HTF

IGNORAR SI:
- OB ya testeado multiples veces
- Solo BOS sin CHoCH
- Sesion asiatica
- Sin FVG ni liquidity sweep
- ATR muy bajo

FORMATO DE RESPUESTA (solo este JSON):
{"decision":"EJECUTAR","puntuacion":8,"confianza":"ALTA","analisis":"explicacion tecnica del setup en 2 oraciones","confluencias":["OB bajista fresco","CHoCH confirmado"],"sl_ajustado":3028.0,"tp1":3010.0,"tp2":3005.0,"zona_precio":"PREMIUM","advertencias":"riesgos a vigilar"}"""

def get_session(hour_utc: int) -> str:
    if 7 <= hour_utc < 12:
        return "Londres"
    elif 12 <= hour_utc < 16:
        return "Overlap Londres-NY"
    elif 16 <= hour_utc < 21:
        return "Nueva York"
    else:
        return "Asia / Fuera de sesion"

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
    sl_dist   = abs(precio - sl) if sl else atr * 1.5
    rr2       = round(precio - sl_dist * 2, 2) if tipo == "SELL" else round(precio + sl_dist * 2, 2)
    rr3       = round(precio - sl_dist * 3, 2) if tipo == "SELL" else round(precio + sl_dist * 3, 2)
    ob_mid    = (ob_hi + ob_lo) / 2 if ob_hi and ob_lo else precio
    zona      = "PREMIUM" if precio > ob_mid else "DISCOUNT"
    cf = []
    if bos:   cf.append("BOS")
    if choch: cf.append("CHoCH")
    if fvg:   cf.append("FVG")
    if liq:   cf.append("Liquidity Sweep")
    return f"SETUP {tipo} XAUUSD M{tf} | Sesion:{sesion} UTC:{hora_utc} | Tendencia:{tendencia} | BOS:{bos} CHoCH:{choch} FVG:{fvg} LiqSweep:{liq} | OB:{ob_lo}-{ob_hi} Precio:{precio} Zona:{zona} | SL:{sl} ATR:{atr} TP2:{rr2} TP3:{rr3} | Confluencias:{','.join(cf) if cf else 'ninguna'} | Responde solo JSON."

def analyze(data: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": SMC_SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": build_prompt(data)}]}],
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

def send_telegram(message: str):
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")

def format_telegram(data: dict, result: dict) -> str:
    tipo      = data.get("tipo", "?")
    precio    = data.get("precio", 0)
    tf        = data.get("timeframe", "?")
    decision  = result.get("decision", "?")
    puntuacion= result.get("puntuacion", 0)
    confianza = result.get("confianza", "?")
    analisis  = result.get("analisis", "")
    confluencias = result.get("confluencias", [])
    sl        = result.get("sl_ajustado", 0)
    tp1       = result.get("tp1", 0)
    tp2       = result.get("tp2", 0)
    zona      = result.get("zona_precio", "?")
    adv       = result.get("advertencias", "")
    hora      = datetime.utcnow().strftime("%d/%m %H:%M")
    emoji_tipo = "🔴" if tipo == "SELL" else "🟢"
    emoji_dec  = "✅" if decision == "EJECUTAR" else "⏳" if decision == "ESPERAR" else "❌"
    cf_text = "\n".join(f"  • {c}" for c in confluencias) if confluencias else "  • Ninguna"
    return f"""{emoji_tipo} <b>SMC GOLD — {tipo} @ {precio}</b>
━━━━━━━━━━━━━━━
{emoji_dec} <b>Decision: {decision}</b>
⭐ Puntuacion: <b>{puntuacion}/10</b> | Confianza: {confianza}
📊 Zona: {zona} | M{tf}

💬 {analisis}

🔗 <b>Confluencias:</b>
{cf_text}

💰 <b>Gestion:</b>
  SL: {sl}
  TP1: {tp1} | TP2: {tp2}

⚠️ {adv}
🕐 {hora} UTC
━━━━━━━━━━━━━━━"""

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "Sin datos"}), 400
    print(f"Senal recibida: {data.get('tipo')} @ {data.get('precio')}")
    try:
        result = analyze(data)
        decision = result.get("decision", "?")
        puntuacion = result.get("puntuacion", 0)
        print(f"IA: {decision} {puntuacion}/10 | Confianza: {result.get('confianza')}")
        msg = format_telegram(data, result)
        send_telegram(msg)
        return jsonify({"status": "ok", "decision": decision, "puntuacion": puntuacion, "confianza": result.get("confianza"), "resultado": result})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/test", methods=["GET"])
def test():
    data = {
        "tipo": "SELL", "precio": 3020.50, "sl": 3028.00,
        "atr": 4.20, "tendencia": -1, "timeframe": "5",
        "bos": True, "choch": True, "fvg": True, "liq_sweep": True,
        "ob_hi": 3025.00, "ob_lo": 3021.50
    }
    result = analyze(data)
    msg = format_telegram(data, result)
    send_telegram(msg)
    print(f"TEST resultado: {result}")
    return jsonify({"test": "ok", "resultado": result})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "modelo": "gemini-2.5-flash-lite",
        "gemini": bool(GEMINI_API_KEY),
        "telegram": bool(os.getenv("TELEGRAM_TOKEN")),
        "hora_utc": datetime.utcnow().strftime("%H:%M:%S")
    })

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "SMC Gold IA corriendo"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
