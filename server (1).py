"""
SMC Gold IA — Gemini 2.5 Flash Vision
Prompt ultra corto para evitar truncamiento JSON
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
    """Extrae y repara JSON de la respuesta de Gemini."""
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

    # JSON incompleto — intentar reparar
    if s != -1:
        fragment = text[s:]
        opens  = fragment.count('{')
        closes = fragment.count('}')
        if opens > closes:
            fragment += '}' * (opens - closes)
            try:
                return json.loads(fragment)
            except:
                pass

        # Extraer campos manualmente si el JSON está muy roto
        result = {}
        for field, pattern in [
            ('d',    r'"d"\s*:\s*"(\w+)"'),
            ('dir',  r'"dir"\s*:\s*"(\w+)"'),
            ('pts',  r'"pts"\s*:\s*(\d+)'),
            ('conf', r'"conf"\s*:\s*"(\w+)"'),
            ('por',  r'"por"\s*:\s*"([^"]*)"'),
            ('zona', r'"zona"\s*:\s*"(\w+)"'),
        ]:
            m = re.search(pattern, text)
            if m:
                result[field] = m.group(1)

        if 'd' in result or 'dir' in result:
            return result

    raise ValueError(f"No se pudo extraer JSON: {text[:200]}")

def call_gemini(images, timeframes):
    tf_str = ", ".join([f"M{t}" if str(t).isdigit() else str(t) for t in timeframes])
    sesion = get_session()

    # Prompt ultra corto — menos texto = menos probabilidad de truncar
    prompt = f"""Analiza este chart de XAUUSD (Oro) con SMC. TF: {tf_str}. Sesion: {sesion}.

Responde SOLO este JSON (nada más, ni una palabra extra):
{{"d":"ESPERAR","dir":"NEUTRAL","pts":5,"conf":"MEDIA","por":"razon corta","sl":0.0,"tp1":0.0,"tp2":0.0,"zona":"EQUILIBRIO","cf":["factor1"],"adv":"advertencia corta"}}

d=EJECUTAR/ESPERAR/IGNORAR, dir=SELL/BUY/NEUTRAL, pts=1-10, conf=ALTA/MEDIA/BAJA"""

    parts = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": {"mime_type": img["mime"], "data": img["data"]}})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature":      0.1,
            "maxOutputTokens":  400,
            "responseMimeType": "application/json"
        }
    }

    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()

    raw_parts = resp.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in raw_parts)
    print(f"📝 Gemini ({len(text)} chars): {text[:500]}")

    raw = extract_json(text)

    # Normalizar a nombres completos
    return {
        "decision":     raw.get("d",    raw.get("decision",    "ESPERAR")),
        "direccion":    raw.get("dir",  raw.get("direccion",   "NEUTRAL")),
        "puntuacion":   int(raw.get("pts",  raw.get("puntuacion",  5))),
        "confianza":    raw.get("conf", raw.get("confianza",   "MEDIA")),
        "analisis":     raw.get("por",  raw.get("analisis",    "")),
        "sl_ajustado":  float(raw.get("sl",   raw.get("sl_ajustado", 0))),
        "tp1":          float(raw.get("tp1",  0)),
        "tp2":          float(raw.get("tp2",  0)),
        "zona_precio":  raw.get("zona", raw.get("zona_precio", "EQUILIBRIO")),
        "confluencias": raw.get("cf",   raw.get("confluencias", [])),
        "advertencias": raw.get("adv",  raw.get("advertencias", "")),
        "sesion":       sesion
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
💰 SL={r.get('sl_ajustado',0)} TP1={r.get('tp1',0)} TP2={r.get('tp2',0)}
⚠️  {r.get('advertencias','')}
{'='*50}
""")

@app.route("/analyze-chart", methods=["POST"])
def analyze_chart():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400

    tfs    = data.get("timeframes", ["15", "240"])
    images = data.get("imagenes", [])

    # Compatibilidad con formato anterior
    if not images and data.get("imagen_base64"):
        images = [{"mime": data.get("imagen_mime","image/png"), "data": data["imagen_base64"]}]

    print(f"\n📨 Análisis | TFs: {tfs} | Imágenes: {len(images)} | Sesión: {get_session()}")

    if not images:
        return jsonify({"error": "Sube al menos una imagen del chart"}), 400

    try:
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
        "status":   "✅ corriendo",
        "modelo":   "gemini-2.5-flash-vision (gratis)",
        "gemini":   "configurado" if GEMINI_API_KEY else "❌ FALTA API KEY",
        "sesion":   get_session(),
        "hora_utc": datetime.utcnow().strftime("%H:%M:%S")
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SMC Gold Vision | Gemini: {'✅' if GEMINI_API_KEY else '❌'} | Puerto: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
