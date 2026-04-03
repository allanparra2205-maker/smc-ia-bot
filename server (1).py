"""
SMC Gold IA — Gemini 2.5 Flash Vision
Soporte múltiples imágenes (HTF + LTF)
JSON simplificado para evitar truncamiento
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
    # Limpiar markdown
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    # Intentar parsear directo
    try:
        return json.loads(text)
    except:
        pass

    # Buscar entre { y }
    s = text.find('{')
    e = text.rfind('}') + 1
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e])
        except:
            pass

    # Si el JSON está incompleto, intentar repararlo
    if s != -1:
        fragment = text[s:]
        # Contar llaves abiertas
        opens  = fragment.count('{')
        closes = fragment.count('}')
        if opens > closes:
            fragment += '}' * (opens - closes)
            try:
                return json.loads(fragment)
            except:
                pass

    raise ValueError(f"JSON inválido: {text[:300]}")

def build_prompt(timeframes, n_images):
    tf_str  = ", ".join([f"M{t}" if str(t).isdigit() else str(t) for t in timeframes])
    sesion  = get_session()
    img_txt = f"{n_images} imagen(es) del chart" if n_images > 1 else "1 imagen del chart"

    return f"""Eres experto en Smart Money Concepts analizando XAUUSD (Oro).
Se te envía {img_txt}. Timeframes: {tf_str}. Sesión: {sesion}.

Analiza y decide: ¿hay setup de VENTA, COMPRA, o hay que ESPERAR?

Busca: CHoCH, BOS, Order Blocks, FVG, barridos de liquidez, zona premium/discount.

IMPORTANTE: Responde SOLO con este JSON corto, sin texto antes ni después:
{{"d":"EJECUTAR","dir":"SELL","pts":8,"conf":"ALTA","por":"Explicación corta del setup en máximo 2 oraciones","sl":0.0,"tp1":0.0,"tp2":0.0,"zona":"PREMIUM","cf":["factor1","factor2","factor3"],"adv":"Riesgo a vigilar"}}

Donde "d" es EJECUTAR/ESPERAR/IGNORAR y "dir" es SELL/BUY/NEUTRAL."""

def call_gemini(images, timeframes):
    """Llama a Gemini con 1 o más imágenes."""
    prompt = build_prompt(timeframes, len(images))

    parts = [{"text": prompt}]
    for img in images:
        parts.append({
            "inline_data": {
                "mime_type": img["mime"],
                "data":      img["data"]
            }
        })

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature":     0.1,
            "maxOutputTokens": 500,
            "responseMimeType": "application/json"
        }
    }

    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()

    raw_parts = resp.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in raw_parts)
    print(f"📝 Gemini raw ({len(text)} chars): {text[:400]}")

    result = extract_json(text)

    # Normalizar campos cortos a nombres completos
    return {
        "decision":    result.get("d", result.get("decision", "ESPERAR")),
        "direccion":   result.get("dir", result.get("direccion", "NEUTRAL")),
        "puntuacion":  result.get("pts", result.get("puntuacion", 5)),
        "confianza":   result.get("conf", result.get("confianza", "MEDIA")),
        "analisis":    result.get("por", result.get("analisis", "")),
        "sl_ajustado": result.get("sl", result.get("sl_ajustado", 0)),
        "tp1":         result.get("tp1", 0),
        "tp2":         result.get("tp2", 0),
        "zona_precio": result.get("zona", result.get("zona_precio", "EQUILIBRIO")),
        "confluencias": result.get("cf", result.get("confluencias", [])),
        "advertencias": result.get("adv", result.get("advertencias", "")),
        "sesion":      get_session()
    }

def print_result(r):
    dec   = r.get("decision","?")
    emoji = "✅" if dec == "EJECUTAR" else "⏳" if dec == "ESPERAR" else "❌"
    print(f"""
{'='*50}
{emoji} {dec} — {r.get('direccion','?')} | {r.get('puntuacion',0)}/10 | {r.get('confianza','?')}
📊 Zona: {r.get('zona_precio','?')} | Sesión: {r.get('sesion','?')}
💬 {r.get('analisis','')}
🔗 {', '.join(r.get('confluencias',[]))}
💰 SL={r.get('sl_ajustado',0)} | TP1={r.get('tp1',0)} | TP2={r.get('tp2',0)}
⚠️  {r.get('advertencias','')}
{'='*50}
""")

@app.route("/analyze-chart", methods=["POST"])
def analyze_chart():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400

    tfs    = data.get("timeframes", ["15", "240"])
    images = data.get("imagenes", [])   # Lista de {mime, data}

    # Compatibilidad con formato anterior (una sola imagen)
    if not images and data.get("imagen_base64"):
        images = [{"mime": data.get("imagen_mime","image/png"), "data": data["imagen_base64"]}]

    print(f"\n📨 Análisis | TFs: {tfs} | Imágenes: {len(images)} | Sesión: {get_session()}")

    try:
        if not images:
            return jsonify({"error": "Sube al menos una imagen del chart para analizar"}), 400

        result = call_gemini(images, tfs)
        print_result(result)
        result["timeframes_analizados"] = tfs
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":  "✅ corriendo",
        "modelo":  "gemini-2.5-flash-vision",
        "gemini":  "configurado" if GEMINI_API_KEY else "❌ FALTA API KEY",
        "sesion":  get_session(),
        "hora_utc": datetime.utcnow().strftime("%H:%M:%S")
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SMC Gold Vision | Gemini: {'✅' if GEMINI_API_KEY else '❌'} | Puerto: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
