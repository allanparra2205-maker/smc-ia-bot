"""
SMC Gold IA Server — Gemini 2.5 Flash Vision
Analiza imágenes de charts con SMC
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

SMC_VISION_PROMPT = """
Eres un trader experto en Smart Money Concepts (SMC) analizando XAUUSD (Oro).

Analiza el chart que te envío e identifica:

1. ESTRUCTURA: ¿Hay BOS o CHoCH visible? ¿Cuál es la tendencia actual?
2. ORDER BLOCKS: ¿Hay OBs relevantes? ¿En qué niveles de precio?
3. FAIR VALUE GAPS: ¿Hay FVGs sin rellenar?
4. LIQUIDEZ: ¿Hubo barrido de liquidez reciente?
5. ZONA: ¿El precio está en zona Premium o Discount?
6. SESGO: ¿La estructura favorece compra o venta?
7. SETUP: ¿Hay un setup válido ahora? ¿O hay que esperar?

Los timeframes analizados son: {timeframes}
El usuario también reporta: {contexto}

DECISIÓN FINAL:
- EJECUTAR: hay setup claro con confluencias
- ESPERAR: la estructura está formándose, esperar confirmación
- IGNORAR: no hay setup válido, riesgo alto

RESPONDE SOLO CON ESTE JSON (sin texto antes ni después):
{{"decision":"EJECUTAR","puntuacion":8,"confianza":"ALTA","analisis":"Descripción detallada del setup visto en el chart","confluencias":["CHoCH confirmado","OB bajista fresco","FVG presente"],"sl_ajustado":0.0,"tp1":0.0,"tp2":0.0,"zona_precio":"PREMIUM","advertencias":"Condiciones a vigilar","timeframes_analizados":["M5","M15","H4"],"sesgo":"BAJISTA"}}
"""

SMC_TEXT_PROMPT = """
Eres un trader experto en Smart Money Concepts (SMC) analizando XAUUSD (Oro).

El usuario reporta este contexto del chart:
- Timeframes: {timeframes}
- CHoCH detectado: {choch}
- BOS detectado: {bos}
- Fair Value Gap: {fvg}
- Liquidity Sweep: {liq}
- Order Block visible: {ob}
- Zona Premium: {premium}

Basándote en estos datos, evalúa el setup SMC y responde SOLO con este JSON:
{{"decision":"EJECUTAR","puntuacion":7,"confianza":"MEDIA","analisis":"Análisis del setup","confluencias":["factor1","factor2"],"sl_ajustado":0.0,"tp1":0.0,"tp2":0.0,"zona_precio":"PREMIUM","advertencias":"advertencias","timeframes_analizados":["M15","H4"],"sesgo":"BAJISTA"}}
"""

def get_session():
    h = datetime.utcnow().hour
    if 7 <= h < 12:    return "Londres"
    elif 12 <= h < 16: return "Overlap Londres-NY"
    elif 16 <= h < 21: return "Nueva York"
    else:              return "Asia"

def extract_json(text):
    # Buscar JSON con "decision" en el texto
    matches = re.findall(r'\{[^{}]*"decision"[^{}]*\}', text, re.DOTALL)
    if matches:
        for m in reversed(matches):
            try: return json.loads(m)
            except: continue
    # Buscar entre primera { y última }
    s = text.find('{')
    e = text.rfind('}') + 1
    if s != -1 and e > s:
        try: return json.loads(text[s:e])
        except: pass
    raise ValueError(f"No JSON en: {text[:300]}")

def call_gemini(contents):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": contents}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1200}
    }
    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts)
    print(f"📝 Gemini: {text[:500]}")
    return extract_json(text)

def print_result(result):
    dec = result.get("decision", "?")
    dec_e = "✅" if dec == "EJECUTAR" else "⏳" if dec == "ESPERAR" else "❌"
    print(f"""
{'='*50}
{dec_e} DECISIÓN: {dec} | {result.get('puntuacion',0)}/10 | {result.get('confianza','?')}
📊 Sesgo: {result.get('sesgo','?')} | Zona: {result.get('zona_precio','?')}
💬 {result.get('analisis','')}
🔗 {', '.join(result.get('confluencias',[]))}
💰 SL={result.get('sl_ajustado',0)} TP1={result.get('tp1',0)} TP2={result.get('tp2',0)}
⚠️  {result.get('advertencias','')}
{'='*50}
""")

# ─── RUTA PRINCIPAL: ANALIZAR CHART CON IMAGEN ───────────────
@app.route("/analyze-chart", methods=["POST"])
def analyze_chart():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400

    tfs       = data.get("timeframes", ["M15","H4"])
    ctx       = data.get("contexto", {})
    tiene_img = data.get("tiene_imagen", False)
    img_b64   = data.get("imagen_base64")
    img_mime  = data.get("imagen_mime", "image/png")
    sesion    = get_session()

    tf_str  = ", ".join([f"M{t}" if str(t).isdigit() else t for t in tfs])
    ctx_str = f"CHoCH:{ctx.get('choch',False)}, BOS:{ctx.get('bos',False)}, FVG:{ctx.get('fvg',False)}, LiqSweep:{ctx.get('liq_sweep',False)}, OB:{ctx.get('ob',False)}, Premium:{ctx.get('premium',False)}"

    print(f"\n📨 Análisis | TFs: {tf_str} | Imagen: {tiene_img} | Sesión: {sesion}")

    try:
        if tiene_img and img_b64:
            # Con imagen — Gemini Vision
            print("🖼️ Analizando con imagen...")
            prompt = SMC_VISION_PROMPT.format(timeframes=tf_str, contexto=ctx_str)
            contents = [
                {"text": prompt},
                {"inline_data": {"mime_type": img_mime, "data": img_b64}}
            ]
        else:
            # Sin imagen — solo texto
            print("📝 Analizando con contexto textual...")
            prompt = SMC_TEXT_PROMPT.format(
                timeframes=tf_str,
                choch=ctx.get('choch', False),
                bos=ctx.get('bos', False),
                fvg=ctx.get('fvg', False),
                liq=ctx.get('liq_sweep', False),
                ob=ctx.get('ob', False),
                premium=ctx.get('premium', False)
            )
            contents = [{"text": prompt}]

        result = call_gemini(contents)
        result["timeframes_analizados"] = tfs
        result["sesion"] = sesion
        print_result(result)
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

# ─── RUTA LEGACY: SEÑAL MANUAL ───────────────────────────────
@app.route("/signal", methods=["POST"])
def receive_signal():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No JSON"}), 400
    print(f"\n📨 Señal manual: {data.get('tipo','?')} @ {data.get('precio','?')}")
    try:
        ctx = data
        prompt = SMC_TEXT_PROMPT.format(
            timeframes=data.get('timeframe','M15'),
            choch=data.get('choch', False),
            bos=data.get('bos', False),
            fvg=data.get('fvg', False),
            liq=data.get('liq_sweep', False),
            ob=True,
            premium=(data.get('tendencia',0) == -1)
        )
        result = call_gemini([{"text": prompt}])
        print_result(result)
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
        "hora_utc": datetime.utcnow().strftime("%H:%M:%S"),
        "sesion":   get_session()
    })

@app.route("/test", methods=["GET"])
def test():
    prompt = SMC_TEXT_PROMPT.format(
        timeframes="M5, M15, H4",
        choch=True, bos=True, fvg=True, liq=True, ob=True, premium=True
    )
    result = call_gemini([{"text": prompt}])
    print_result(result)
    return jsonify({"test": "ok", "resultado": result})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SMC Gold IA Vision | Gemini: {'✅' if GEMINI_API_KEY else '❌'} | Puerto: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
