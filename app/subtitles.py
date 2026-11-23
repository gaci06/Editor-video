"""Genera subtítulos .ass (Advanced SubStation) con estilos animados para Reels/TikTok."""
import re

from .media import FORMATOS

ESTILO_POR_DEFECTO = {
    "preset": "tiktok",          # tiktok | karaoke | palabra | frase
    "fuente": "Anton",           # Anton | Archivo Black | Poppins
    "tamano": 110,               # px para un vídeo de 1080 de ancho
    "color": "#FFFFFF",
    "resaltado": "#FFE400",
    "borde_color": "#000000",
    "borde": 6,
    "sombra": 2,
    "posicion": "centro",        # abajo | centro | arriba
    "mayusculas": True,
    "animacion": "pop",          # pop | fade | ninguna
    "palabras_por_bloque": 3,
}

PRESETS = {
    "tiktok": "Bloques de 2-4 palabras; la palabra que suena se colorea y crece",
    "karaoke": "La frase entera; el color se va rellenando al ritmo de cada palabra",
    "palabra": "Una sola palabra grande en pantalla cada vez, con golpe",
    "frase": "La frase completa aparece y desaparece (estilo subtítulo clásico)",
}
FUENTES = ["Anton", "Archivo Black", "Poppins"]


def _color(hex_, alpha=0):
    hex_ = (hex_ or "#FFFFFF").lstrip("#")
    if len(hex_) != 6:
        hex_ = "FFFFFF"
    r, g, b = hex_[0:2], hex_[2:4], hex_[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _t(seg):
    seg = max(0.0, seg)
    h = int(seg // 3600)
    m = int(seg % 3600 // 60)
    s = seg % 60
    cs = int(round((s - int(s)) * 100))
    s = int(s)
    if cs == 100:
        s, cs = s + 1, 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _limpiar(txt):
    return txt.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def palabras_de_linea(linea):
    """Devuelve las palabras con tiempos. Si el usuario cambió el texto, reparte los tiempos
    de forma proporcional a la longitud de cada palabra dentro de la duración de la línea."""
    texto = linea.get("texto", "").split()
    pal = linea.get("palabras") or []
    if [p["w"] for p in pal] == texto and pal:
        return pal
    if not texto:
        return []
    ini, fin = float(linea["inicio"]), float(linea["fin"])
    pesos = [len(w) + 2 for w in texto]
    total = sum(pesos)
    out, t = [], ini
    for w, p in zip(texto, pesos):
        d = (fin - ini) * p / total
        out.append({"w": w, "t0": round(t, 3), "t1": round(t + d, 3)})
        t += d
    return out


def generar_ass(lineas, estilo, formato="9:16"):
    e = {**ESTILO_POR_DEFECTO, **(estilo or {})}
    W, H = FORMATOS.get(formato, FORMATOS["9:16"])
    escala = W / 1080
    tam = int(e["tamano"] * escala)
    an = {"abajo": 2, "centro": 5, "arriba": 8}.get(e["posicion"], 5)
    margen_v = int(H * 0.14) if an != 5 else 0
    margen_h = int(W * 0.08)
    borde = max(0, float(e["borde"])) * escala
    sombra = max(0, float(e["sombra"])) * escala
    may = bool(e["mayusculas"])
    col, res = _color(e["color"]), _color(e["resaltado"])
    preset = e["preset"] if e["preset"] in PRESETS else "tiktok"
    anim = e["animacion"]

    # Para karaoke: Primary = color tras sonar, Secondary = color antes de sonar
    primario, secundario = (res, col) if preset == "karaoke" else (col, res)
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{e['fuente']},{tam},{primario},{secundario},{_color(e['borde_color'])},{_color('#000000', 0x80)},0,0,0,0,100,100,0,0,1,{borde:.1f},{sombra:.1f},{an},{margen_h},{margen_h},{margen_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def entrada():
        if anim == "pop":
            return r"{\fscx70\fscy70\t(0,110,\fscx108\fscy108)\t(110,180,\fscx100\fscy100)}"
        if anim == "fade":
            return r"{\fad(120,120)}"
        return ""

    def txt(w):
        w = _limpiar(w)
        return w.upper() if may else w

    eventos = []
    for linea in sorted(lineas, key=lambda l: l["inicio"]):
        pal = palabras_de_linea(linea)
        if not pal:
            continue
        ini, fin = float(linea["inicio"]), float(linea["fin"])

        if preset == "frase":
            eventos.append((ini, fin, entrada() + " ".join(txt(p["w"]) for p in pal)))

        elif preset == "karaoke":
            partes = []
            cursor = ini
            for p in pal:
                if p["t0"] > cursor:  # silencio antes de la palabra
                    partes.append(r"{\k%d}" % round((p["t0"] - cursor) * 100))
                partes.append(r"{\kf%d}%s " % (max(1, round((p["t1"] - p["t0"]) * 100)), txt(p["w"])))
                cursor = p["t1"]
            eventos.append((ini, fin, entrada() + "".join(partes).strip()))

        elif preset == "palabra":
            for i, p in enumerate(pal):
                hasta = pal[i + 1]["t0"] if i + 1 < len(pal) else fin
                eventos.append((p["t0"], max(hasta, p["t1"]), entrada() + txt(p["w"])))

        else:  # tiktok
            n = max(1, int(e["palabras_por_bloque"]))
            bloques = [pal[i:i + n] for i in range(0, len(pal), n)]
            for b_i, bloque in enumerate(bloques):
                fin_bloque = bloques[b_i + 1][0]["t0"] if b_i + 1 < len(bloques) else fin
                for i, p in enumerate(bloque):
                    hasta = bloque[i + 1]["t0"] if i + 1 < len(bloque) else fin_bloque
                    trozos = []
                    for j, q in enumerate(bloque):
                        if j == i:
                            trozos.append(r"{\c&H%s&\fscx112\fscy112}%s{\r}" % (res[4:], txt(q["w"])))
                        else:
                            trozos.append(txt(q["w"]))
                    pre = entrada() if i == 0 else ""
                    eventos.append((p["t0"], max(hasta, p["t1"]), pre + " ".join(trozos)))

    cuerpo = "\n".join(
        f"Dialogue: 0,{_t(a)},{_t(b)},Base,,0,0,0,,{t}" for a, b, t in eventos if b > a
    )
    return cab + cuerpo + "\n"


def agrupar_en_lineas(palabras, max_palabras=6, pausa=0.6):
    """Convierte una lista de palabras con tiempo en líneas cortas, cortando en pausas y en puntuación."""
    lineas, actual = [], []
    for i, p in enumerate(palabras):
        if actual and (p["t0"] - actual[-1]["t1"] > pausa or len(actual) >= max_palabras):
            lineas.append(actual)
            actual = []
        actual.append(p)
        if re.search(r"[.!?…,;:]$", p["w"]) and len(actual) >= 2:
            lineas.append(actual)
            actual = []
    if actual:
        lineas.append(actual)
    return [
        {"inicio": l[0]["t0"], "fin": l[-1]["t1"], "texto": " ".join(p["w"] for p in l), "palabras": l}
        for l in lineas
    ]
