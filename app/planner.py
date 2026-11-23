"""Convierte lo que pide el usuario en un plan de edición (JSON) usando la API de Claude.

La IA no toca el vídeo: solo decide parámetros. Luego montaje.py y media.py los ejecutan.
Sin API key se usa un plan automático razonable.
"""
import json
import os
import re

from .subtitles import ESTILO_POR_DEFECTO, FUENTES, PRESETS

MODELO = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

SISTEMA = """Eres el director creativo de un editor de vídeo para Reels y TikTok.
Recibes los clips del usuario, el análisis de la canción (BPM, beats, energía por segundo y la letra con tiempos)
y lo que el usuario pide. Devuelves SOLO un objeto JSON (sin texto alrededor, sin ```), con esta forma:

{
  "inicio_cancion": número de segundos donde empieza a sonar la canción (elige el trozo que mejor encaje: p. ej. el estribillo o la subida de energía),
  "duracion": segundos del vídeo final,
  "encuadre": "llenar" (recorta para ocupar toda la pantalla) o "ajustar" (vídeo entero con fondo desenfocado),
  "orden_clips": [índices de clips en el orden en que deben aparecer; puedes omitir clips que no encajen],
  "rangos_clips": [{"clip": índice, "desde": s, "hasta": s}]  (opcional, para usar solo una parte de un clip),
  "ritmo": [{"hasta": segundo del vídeo final, "cada_beats": cada cuántos beats se corta en ese tramo}],
       (más cortes = más energía: 1-2 beats en partes intensas, 4-8 en partes tranquilas; sin canción usa {"cada_segundos": n} o [] para clips enteros)
  "subtitulos": true/false,
  "estilo": {
     "preset": uno de PRESETS,
     "fuente": una de FUENTES,
     "tamano": 60-160 (px para 1080 de ancho),
     "color": "#RRGGBB", "resaltado": "#RRGGBB", "borde_color": "#RRGGBB",
     "borde": 0-12, "sombra": 0-8,
     "posicion": "abajo" | "centro" | "arriba",
     "mayusculas": true/false,
     "animacion": "pop" | "fade" | "ninguna",
     "palabras_por_bloque": 1-5
  },
  "explicacion": "1-2 frases en español contando qué has decidido y por qué"
}

Reglas:
- Respeta lo que el usuario pida aunque contradiga estas sugerencias.
- Ajusta el estilo a la canción: canción enérgica -> cortes rápidos, preset tiktok o palabra, colores intensos; balada -> cortes lentos, karaoke o frase, fade.
- Si hay letra, colócala en un tramo donde haya letra que se entienda (salvo que pida otra cosa).
- Nunca pongas inicio_cancion + duracion por encima de la duración de la canción.
- Si te pasan un plan actual y una petición de cambio, modifica solo lo necesario y conserva el resto."""


def _resumen(clips, analisis, peticion, formato, duracion, plan_actual):
    datos = {
        "peticion_del_usuario": peticion or "(sin indicaciones: hazlo atractivo para redes)",
        "formato": formato,
        "duracion_pedida": duracion or "la que mejor encaje (entre 10 y 60 s si no se dice nada)",
        "clips": [
            {"indice": i, "nombre": c["nombre"], "duracion": c["duracion"],
             "orientacion": "vertical" if c.get("alto", 0) > c.get("ancho", 0) else "horizontal",
             "tiene_audio": c.get("tiene_audio")}
            for i, c in enumerate(clips)
        ],
        "PRESETS": PRESETS,
        "FUENTES": FUENTES,
    }
    can = analisis.get("cancion")
    if can:
        e = can["energia"]
        datos["cancion"] = {
            "duracion": can["duracion"],
            "bpm": can["bpm"],
            "energia_cada_2s": [round(max(e[i:i + 2]), 2) for i in range(0, len(e), 2)],
            "letra_con_tiempos": [
                {"inicio": round(l["inicio"], 1), "fin": round(l["fin"], 1), "texto": l["texto"]}
                for l in analisis.get("lineas_cancion", [])
            ][:120],
        }
    if plan_actual:
        datos["plan_actual"] = {k: plan_actual.get(k) for k in
                                ("inicio_cancion", "duracion", "encuadre", "orden_clips", "rangos_clips",
                                 "ritmo", "subtitulos", "estilo")}
    return json.dumps(datos, ensure_ascii=False)


def _extraer_json(texto):
    texto = re.sub(r"^```(json)?|```$", "", texto.strip(), flags=re.M)
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini < 0 or fin < 0:
        raise ValueError("La IA no devolvió JSON")
    return json.loads(texto[ini:fin + 1])


def _hex(v, defecto):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else defecto


def validar(plan, clips, analisis, base=None):
    """Limpia lo que venga de la IA para que nunca rompa el render."""
    base = base or {}
    out = {**base}
    can = analisis.get("cancion")
    n = len(clips)
    orden = [int(i) for i in plan.get("orden_clips", base.get("orden_clips") or []) if str(i).isdigit() and int(i) < n]
    out["orden_clips"] = orden or list(range(n))
    out["rangos_clips"] = [r for r in plan.get("rangos_clips", base.get("rangos_clips")) or []
                           if isinstance(r, dict) and str(r.get("clip", "")).isdigit() and int(r["clip"]) < n]
    out["encuadre"] = plan.get("encuadre") if plan.get("encuadre") in ("llenar", "ajustar") else base.get("encuadre", "llenar")
    out["subtitulos"] = bool(plan.get("subtitulos", base.get("subtitulos", True)))
    ritmo = plan.get("ritmo", base.get("ritmo") or [])
    out["ritmo"] = [r for r in ritmo if isinstance(r, dict)] if isinstance(ritmo, list) else []
    dur = plan.get("duracion", base.get("duracion"))
    try:
        dur = float(dur)
    except (TypeError, ValueError):
        dur = 0
    ini = float(plan.get("inicio_cancion", base.get("inicio_cancion", 0)) or 0)
    if can:
        total = can["duracion"]
        if dur:
            dur = min(dur, total)
            ini = min(max(0.0, ini), total - dur)  # si se sale, adelantamos el inicio
        else:
            ini = min(max(0.0, ini), max(0.0, total - 3))
            dur = total - ini
    out["inicio_cancion"] = round(ini, 2)
    out["duracion"] = round(dur, 2) if dur else 0

    e = {**ESTILO_POR_DEFECTO, **(base.get("estilo") or {}), **(plan.get("estilo") or {})}
    e["preset"] = e["preset"] if e["preset"] in PRESETS else "tiktok"
    e["fuente"] = e["fuente"] if e["fuente"] in FUENTES else "Anton"
    for k in ("color", "resaltado", "borde_color"):
        e[k] = _hex(e[k], ESTILO_POR_DEFECTO[k])
    e["tamano"] = int(min(200, max(30, float(e["tamano"]))))
    e["borde"] = min(15, max(0, float(e["borde"])))
    e["sombra"] = min(10, max(0, float(e["sombra"])))
    e["posicion"] = e["posicion"] if e["posicion"] in ("abajo", "centro", "arriba") else "centro"
    e["animacion"] = e["animacion"] if e["animacion"] in ("pop", "fade", "ninguna") else "pop"
    e["palabras_por_bloque"] = int(min(6, max(1, int(e["palabras_por_bloque"]))))
    e["mayusculas"] = bool(e["mayusculas"])
    out["estilo"] = e
    out["explicacion"] = str(plan.get("explicacion", ""))[:500]
    return out


def plan_automatico(clips, analisis, duracion):
    """Plan sin IA: el tramo más enérgico de la canción y cortes al ritmo."""
    can = analisis.get("cancion")
    plan = {"orden_clips": list(range(len(clips))), "encuadre": "llenar", "subtitulos": True,
            "estilo": dict(ESTILO_POR_DEFECTO)}
    if can:
        dur = float(duracion or min(30, can["duracion"]))
        e = can["energia"]
        ventana = max(1, int(dur))
        if len(e) > ventana:
            # segundos con letra cantada: preferimos tramos con energía Y con letra
            con_letra = [0] * len(e)
            for l in analisis.get("lineas_cancion", []):
                for s in range(int(l["inicio"]), min(len(e), int(l["fin"]) + 1)):
                    con_letra[s] = 1
            hay_letra = any(con_letra)
            sumas = [sum(e[i:i + ventana]) * ((0.4 + sum(con_letra[i:i + ventana]) / ventana) if hay_letra else 1)
                     for i in range(0, len(e) - ventana + 1)]
            ini = max(range(len(sumas)), key=lambda i: sumas[i])
        else:
            ini = 0
        rapido = 2 if can["bpm"] < 110 else 4
        plan.update(inicio_cancion=float(ini), duracion=dur,
                    ritmo=[{"hasta": dur * 0.3, "cada_beats": rapido * 2}, {"hasta": 9999, "cada_beats": rapido}])
    else:
        plan.update(duracion=float(duracion or 0), ritmo=[])
    plan["explicacion"] = "Plan automático (sin IA): tramo con más energía de la canción y cortes al ritmo."
    return plan


def planificar(clips, analisis, peticion, formato, duracion, plan_actual=None):
    clave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not clave:
        base = plan_actual or plan_automatico(clips, analisis, duracion)
        return validar(base, clips, analisis), "sin_ia"
    import anthropic
    cliente = anthropic.Anthropic(api_key=clave)
    resp = cliente.messages.create(
        model=MODELO,
        max_tokens=2000,
        system=SISTEMA,
        messages=[{"role": "user", "content": _resumen(clips, analisis, peticion, formato, duracion, plan_actual)}],
    )
    texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    bruto = _extraer_json(texto)
    if duracion and not plan_actual:
        bruto["duracion"] = duracion  # lo que pide el usuario manda
    return validar(bruto, clips, analisis, base=plan_actual), "ia"
