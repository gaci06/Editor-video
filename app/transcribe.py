"""Transcripción con faster-whisper (CPU) y alineación con una letra dada por el usuario."""
import difflib
import re
import unicodedata
from pathlib import Path

from .subtitles import agrupar_en_lineas

MODELOS_DIR = Path(__file__).resolve().parent.parent / "modelos"
_cache = {}


def _modelo(nombre):
    if nombre not in _cache:
        from faster_whisper import WhisperModel  # import tardío: tarda en cargar
        _cache.clear()  # solo un modelo en memoria a la vez
        _cache[nombre] = WhisperModel(nombre, device="cpu", compute_type="int8",
                                      download_root=str(MODELOS_DIR))
    return _cache[nombre]


def transcribir(ruta_audio, modelo="small", idioma="es", pista=None, es_cancion=False, progreso=None):
    """Devuelve una lista de palabras [{w, t0, t1}]."""
    if progreso:
        progreso(0.02, f"Cargando modelo de voz '{modelo}' (la primera vez se descarga)")
    m = _modelo(modelo)
    segmentos, info = m.transcribe(
        str(ruta_audio),
        language=idioma or None,
        word_timestamps=True,
        vad_filter=not es_cancion,       # en canciones el VAD corta trozos cantados
        initial_prompt=(pista or None),
        beam_size=5,
        condition_on_previous_text=False,
    )
    palabras = []
    total = max(1.0, info.duration or 1.0)
    for seg in segmentos:
        for w in seg.words or []:
            txt = w.word.strip()
            if txt:
                palabras.append({"w": txt, "t0": round(w.start, 3), "t1": round(max(w.end, w.start + 0.05), 3)})
        if progreso:
            progreso(min(0.99, seg.end / total), f"Transcribiendo… {int(seg.end)}s de {int(total)}s")
    return palabras


def _norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", w)


def lineas_de_letra(letra):
    out = []
    for l in (letra or "").splitlines():
        l = l.strip()
        if not l or re.fullmatch(r"[\[(].*[\])]", l):  # [Estribillo], (x2)...
            continue
        out.append(l)
    return out


def alinear_letra(palabras, letra):
    """Pone tiempos a la letra que ha escrito el usuario usando lo que reconoció Whisper.

    Las palabras que coinciden heredan el tiempo reconocido; las que no, se interpolan
    entre sus vecinas. Devuelve líneas respetando los saltos de línea de la letra.
    """
    lineas = [l.split() for l in lineas_de_letra(letra)]
    letra_pal = [(i, w) for i, l in enumerate(lineas) for w in l]
    if not letra_pal:
        return []
    a = [_norm(p["w"]) for p in palabras]
    b = [_norm(w) for _, w in letra_pal]
    tiempos = [None] * len(b)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            p = palabras[blk.a + k]
            tiempos[blk.b + k] = (p["t0"], p["t1"])
    # interpolar huecos
    conocidos = [i for i, t in enumerate(tiempos) if t]
    if not conocidos:
        return []
    for i in range(len(tiempos)):
        if tiempos[i]:
            continue
        prev = max((k for k in conocidos if k < i), default=None)
        nxt = min((k for k in conocidos if k > i), default=None)
        if prev is None:
            t = tiempos[nxt][0] - 0.35 * (nxt - i)
        elif nxt is None:
            t = tiempos[prev][1] + 0.35 * (i - prev - 1)
        else:
            frac = (i - prev) / (nxt - prev)
            t = tiempos[prev][1] + frac * (tiempos[nxt][0] - tiempos[prev][1])
        tiempos[i] = (max(0, t), max(0, t) + 0.3)
    resultado, idx = [], 0
    for l in lineas:
        pals = []
        for w in l:
            t0, t1 = tiempos[idx]
            pals.append({"w": w, "t0": round(t0, 3), "t1": round(t1, 3)})
            idx += 1
        # orden y sin solapes raros
        for j in range(1, len(pals)):
            if pals[j]["t0"] < pals[j - 1]["t0"]:
                pals[j]["t0"] = pals[j - 1]["t1"]
                pals[j]["t1"] = max(pals[j]["t1"], pals[j]["t0"] + 0.1)
        resultado.append({"inicio": pals[0]["t0"], "fin": max(pals[-1]["t1"], pals[0]["t0"] + 0.3),
                          "texto": " ".join(l), "palabras": pals})
    return resultado


def lineas_en_tramo(lineas, inicio, duracion):
    """Recorta las líneas a [inicio, inicio+duracion] y las desplaza para que empiecen en 0."""
    fin = inicio + duracion
    out = []
    for l in lineas:
        if l["fin"] <= inicio or l["inicio"] >= fin:
            continue
        pals = [{"w": p["w"], "t0": round(max(0, p["t0"] - inicio), 3), "t1": round(min(duracion, p["t1"] - inicio), 3)}
                for p in l["palabras"] if p["t1"] > inicio and p["t0"] < fin]
        if not pals:
            continue
        out.append({"inicio": pals[0]["t0"], "fin": max(pals[-1]["t1"], pals[0]["t0"] + 0.2),
                    "texto": " ".join(p["w"] for p in pals), "palabras": pals})
    return out


def lineas_desde_palabras(palabras, max_palabras=6):
    return agrupar_en_lineas(palabras, max_palabras=max_palabras)
