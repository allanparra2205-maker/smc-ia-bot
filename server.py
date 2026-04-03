"""
SMC Gold IA Server — Gemini 2.5 Flash Vision
La IA ve el chart y decide sola.
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

def get_session():
    h = datetime.utcnow().hour
    if 7 <= h < 12:    return "Londres"
    elif 12 <= h < 16: return "Overlap Londres-NY"
    elif 16 <= h < 21: return "Nueva York"
    else:              return "Asia"

def extract_json(text):
    # Limpiar backticks markdown
    text = re.sub(r'```json', '', text)
    text = re.sub(r'```', '', text)
    text = text.strip()

    # Intentar parsear directo
    try:
        return json.loads(text)
    except:
        pass

    # Buscar el bloque JSON más completo
    start = text.find('{')
    end   = text.rfind('}') + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except:
            pass

    # Buscar con regex
    matches = re.findall(r'\{.*?"decision".*?\}', text, re.DOTALL)
    for m in reversed(matches):
        try:
            return json.loads(m)
        except:
            continue

    raise ValueError(f"No JSON válido en respuesta: {text[:400]}")

def call_gemini_vision(image_b64, image_mime, timeframes):
    tf_str = ", ".join([f"M{t}" if str(t).isdigit() else str(t) for t in timeframes])
    sesion = get_session()

    prompt = f"""Eres un trader experto en Smart Money Concepts (SMC) analizando XAUUSD (Oro).

Analiza este chart del oro y responde con tu análisis SMC completo.

El chart muestra timeframe(s): {tf_str}
Sesión actual: {sesion}

ANALIZA Y DETECTA:
- Tendencia general (alcista/bajista)
- BOS o CHoCH visibles
- Order Blocks relevantes y sus niveles de precio
- Fair Value Gaps sin rellenar
- Barridos de liquidez recientes
- Si el precio está en zona Premium o Discount
- Si hay un setup válido ahora o hay que esperar

DECIDE:
- EJECUTAR: hay setup claro con buenas confluencias SMC
- ESPERAR: estructura formándose, necesita confirmación
- IGNORAR: no hay setup, riesgo muy alto

Responde ÚNICAMENTE con este JSON, sin texto antes ni después:
{{"decision":"EJECUTAR","puntuacion":8,"confianza":"ALTA","analisis":"Descripción clara del setup visto en el chart en 2-3 oraciones","confluencias":["CHoCH bajista confirmado","OB bajista en 3025","FVG presente"],"sl_ajustado":3028.0,"tp1":3010.0,"tp2":3002.0,"zona_precio":"PREMIUM","advertencias":"Qué vigilar","sesgo":"BAJISTA"}}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": image_mime, "data": image_b64}}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1500,
            "responseMimeType": "application/json"
        }
    }

    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()

    parts = resp.json()["candidates"][0]["content"]["parts"]
    text  = "".join(p.get("text", "") for p in parts)
    print(f"📝 Gemini raw: {text[:600]}")
    return extract_json(text)

def call_gemini_text(timeframes):
    tf_str = ", ".join([f"M{t}" if str(t).isdigit() else str(t) for t in timeframes])
    sesion = get_session()

    prompt = f"""Eres un trader experto en SMC analizando XAUUSD.
Sesión actual: {sesion} | Timeframes: {tf_str}
No hay imagen disponible. Da un análisis general de qué buscar en el oro ahora mismo según SMC y la sesión actual.
Responde SOLO con este JSON:
{{"decision":"ESPERAR","puntuacion":5,"confianza":"BAJA","analisis":"Sin imagen no es posible confirmar estructura. Descripción de qué buscar ahora","confluencias":["Sesión activa"],"sl_ajustado":0.0,"tp1":0.0,"tp2":0.0,"zona_precio":"EQUILIBRIO","advertencias":"Sube una imagen del chart para análisis preciso","sesgo":"NEUTRAL"}}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800, "responseMimeType": "application/json"}
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    text  = "".join(p.get("text", "") for p in parts)
    return extract_json(text)

def print_result(result):
    dec   = result.get("decision", "?")
    emoji = "✅" if dec == "EJECUTAR" else "⏳" if dec == "ESPERAR" else "❌"
    print(f"""
{'='*50}
{emoji} {dec} | {result.get('puntuacion',0)}/10 | {result.get('confianza','?')}
📊 Sesgo: {result.get('sesgo','?')} | Zona: {result.get('zona_precio','?')}
💬 {result.get('analisis','')}
🔗 {', '.join(result.get('confluencias',[]))}
💰 SL={result.get('sl_ajustado',0)} TP1={result.get('tp1',0)} TP2={result.get('tp2',0)}
⚠️  {result.get('advertencias','')}
{'='*50}
""")

@app.route("/analyze-chart", methods=["POST"])
def analyze_chart():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400

    tfs     = data.get("timeframes", ["15", "240"])
    img_b64 = data.get("imagen_base64")
    img_mime = data.get("imagen_mime", "image/png")
    tiene_img = bool(img_b64)

    print(f"\n📨 Análisis | TFs: {tfs} | Imagen: {tiene_img} | Sesión: {get_session()}")

    try:
        if tiene_img:
            print("🖼️  Analizando imagen con Gemini Vision...")
            result = call_gemini_vision(img_b64, img_mime, tfs)
        else:
            print("📝 Sin imagen — análisis textual...")
            result = call_gemini_text(tfs)

        result["timeframes_analizados"] = tfs
        result["sesion"] = get_session()
        print_result(result)
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":  "✅ corriendo",
        "modelo":  "gemini-2.5-flash-vision (gratis)",
        "gemini":  "configurado" if GEMINI_API_KEY else "❌ FALTA API KEY",
        "sesion":  get_session(),
        "hora_utc": datetime.utcnow().strftime("%H:%M:%S")
    })

@app.route("/test", methods=["GET"])
def test():
    result = call_gemini_text(["5", "15", "240"])
    print_result(result)
    return jsonify({"test": "ok", "resultado": result})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SMC Gold Vision | Gemini: {'✅' if GEMINI_API_KEY else '❌'} | Puerto: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
