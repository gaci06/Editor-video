"""Servidor local (FastAPI). Guarda cada proyecto en proyectos/<id>/proyecto.json."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import beats, media, montaje, planner, subtitles, transcribe

RAIZ = Path(__file__).resolve().parent.parent
PROYECTOS = RAIZ / "proyectos"
PROYECTOS.mkdir(exist_ok=True)
ENV = RAIZ / ".env"


def cargar_env():
    if ENV.exists():
        for linea in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"')
    planner.MODELO = os.environ.get("CLAUDE_MODEL") or planner.MODELO


cargar_env()
app = FastAPI(title="Editor de vídeo")
app.mount("/media", StaticFiles(directory=PROYECTOS), name="media")

# ---------------------------------------------------------------- trabajos en segundo plano
TRABAJOS = {}
_cola = threading.Lock()  # un trabajo pesado a la vez: la CPU no da para más


def lanzar(funcion, *args):
    tid = uuid.uuid4().hex[:10]
    TRABAJOS[tid] = {"estado": "en_cola", "progreso": 0, "mensaje": "Esperando…", "resultado": None}

    def progreso(p, msg):
        TRABAJOS[tid].update(progreso=round(float(p), 3), mensaje=msg)

    def correr():
        with _cola:
            TRABAJOS[tid]["estado"] = "trabajando"
            try:
                TRABAJOS[tid]["resultado"] = funcion(*args, progreso)
                TRABAJOS[tid].update(estado="hecho", progreso=1)
            except Exception as e:  # noqa: BLE001 - queremos enseñar cualquier error en la interfaz
                traceback.print_exc()
                TRABAJOS[tid].update(estado="error", mensaje=str(e))

    threading.Thread(target=correr, daemon=True).start()
    return {"trabajo": tid}


@app.get("/api/trabajos/{tid}")
def ver_trabajo(tid: str):
    if tid not in TRABAJOS:
        raise HTTPException(404, "Trabajo no encontrado")
    return TRABAJOS[tid]


# ---------------------------------------------------------------- proyectos
def _dir(pid):
    if not re.fullmatch(r"[a-z0-9]{8,16}", pid):
        raise HTTPException(400, "Id no válido")
    d = PROYECTOS / pid
    if not (d / "proyecto.json").exists():
        raise HTTPException(404, "Proyecto no encontrado")
    return d


def leer(pid):
    return json.loads((_dir(pid) / "proyecto.json").read_text(encoding="utf-8"))


def guardar(p):
    p["modificado"] = time.time()
    f = PROYECTOS / p["id"] / "proyecto.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def _nombre_seguro(nombre):
    base = re.sub(r"[^\w.\- ]", "_", Path(nombre).name)[:80]
    return base or "archivo"


@app.get("/api/estado")
def estado():
    return {
        "ia": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "modelo_ia": planner.MODELO,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "presets": subtitles.PRESETS,
        "fuentes": subtitles.FUENTES,
        "formatos": list(media.FORMATOS),
        "estilo_defecto": subtitles.ESTILO_POR_DEFECTO,
    }


@app.post("/api/ajustes")
def ajustes(datos: dict):
    lineas = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    for clave in ("ANTHROPIC_API_KEY", "CLAUDE_MODEL"):
        if clave in datos:
            lineas = [l for l in lineas if not l.startswith(clave + "=")]
            valor = str(datos[clave]).strip()
            if valor:
                lineas.append(f"{clave}={valor}")
            else:
                os.environ.pop(clave, None)
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    cargar_env()
    return estado()


@app.get("/api/proyectos")
def listar():
    out = []
    for d in PROYECTOS.iterdir():
        f = d / "proyecto.json"
        if f.exists():
            p = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": p["id"], "nombre": p["nombre"], "modificado": p.get("modificado", 0),
                        "clips": len(p["clips"]), "miniatura": p["clips"][0]["miniatura"] if p["clips"] else None})
    return sorted(out, key=lambda x: -x["modificado"])


@app.post("/api/proyectos")
def crear_proyecto(datos: dict):
    pid = uuid.uuid4().hex[:12]
    d = PROYECTOS / pid
    (d / "clips").mkdir(parents=True)
    p = {"id": pid, "nombre": (datos.get("nombre") or "Proyecto sin nombre")[:80], "creado": time.time(),
         "clips": [], "cancion": None, "letra": "", "peticion": "", "formato": "9:16", "duracion": 0,
         "idioma": "es", "modelo_voz": "small", "analisis": {}, "plan": None, "subtitulos": [],
         "ultimo_render": None, "exportados": []}
    guardar(p)
    return p


@app.get("/api/proyectos/{pid}")
def ver(pid: str):
    return leer(pid)


CAMPOS_EDITABLES = {"nombre", "letra", "peticion", "formato", "duracion", "idioma", "modelo_voz", "subtitulos"}


@app.put("/api/proyectos/{pid}")
def actualizar(pid: str, datos: dict):
    p = leer(pid)
    for k, v in datos.items():
        if k in CAMPOS_EDITABLES:
            p[k] = v
    if "letra" in datos and p.get("cancion"):
        p["analisis"].pop("lineas_cancion", None)  # hay que realinear con la letra nueva
    if "plan" in datos and p.get("plan"):
        cambios = datos["plan"]
        if "estilo" in cambios:
            p["plan"]["estilo"] = {**p["plan"]["estilo"], **cambios["estilo"]}
        if "segmentos" in cambios:  # edición manual de la línea de tiempo
            segs, t = [], 0.0
            for s in cambios["segmentos"]:
                d = max(0.2, float(s["fin"]) - float(s["inicio"]))
                c = int(s["clip"])
                if 0 <= c < len(p["clips"]):
                    entrada = min(max(0, float(s["entrada"])), max(0, p["clips"][c]["duracion"] - 0.2))
                    segs.append({"clip": c, "entrada": round(entrada, 3), "inicio": round(t, 3), "fin": round(t + d, 3)})
                    t += d
            p["plan"]["segmentos"] = segs
            p["plan"]["duracion"] = round(t, 3)
        for k in ("subtitulos",):
            if k in cambios:
                p["plan"][k] = bool(cambios[k])
    guardar(p)
    return p


@app.post("/api/proyectos/{pid}/clips")
async def subir_clips(pid: str, archivos: list[UploadFile] = File(...)):
    d = _dir(pid)
    p = leer(pid)
    for a in archivos:
        nombre = f"{len(p['clips']):02d}_{_nombre_seguro(a.filename)}"
        destino = d / "clips" / nombre
        with open(destino, "wb") as f:
            shutil.copyfileobj(a.file, f)
        try:
            info = media.analizar(destino)
            if "ancho" not in info:
                raise RuntimeError("no tiene imagen")
            mini = d / "clips" / (destino.stem + ".jpg")
            media.miniatura(destino, mini, segundo=min(0.5, info["duracion"] / 2))
        except Exception as e:  # noqa: BLE001
            destino.unlink(missing_ok=True)
            raise HTTPException(400, f"'{a.filename}' no parece un vídeo válido ({e})")
        p["clips"].append({"nombre": a.filename, "ruta": str(destino),
                           "miniatura": f"/media/{pid}/clips/{mini.name}", **info})
    guardar(p)
    return p


@app.delete("/api/proyectos/{pid}/clips/{indice}")
def quitar_clip(pid: str, indice: int):
    p = leer(pid)
    if not 0 <= indice < len(p["clips"]):
        raise HTTPException(404, "Ese clip no existe")
    p["clips"].pop(indice)
    p["plan"] = None  # los índices cambian: hay que volver a montar
    guardar(p)
    return p


@app.post("/api/proyectos/{pid}/clips/orden")
def ordenar_clips(pid: str, datos: dict):
    p = leer(pid)
    orden = datos.get("orden", [])
    if sorted(orden) != list(range(len(p["clips"]))):
        raise HTTPException(400, "Orden no válido")
    p["clips"] = [p["clips"][i] for i in orden]
    p["plan"] = None
    guardar(p)
    return p


@app.post("/api/proyectos/{pid}/cancion")
async def subir_cancion(pid: str, archivo: UploadFile = File(...)):
    d = _dir(pid)
    p = leer(pid)
    destino = d / ("cancion_" + _nombre_seguro(archivo.filename))
    with open(destino, "wb") as f:
        shutil.copyfileobj(archivo.file, f)
    try:
        info = media.analizar(destino)
        if not info["tiene_audio"]:
            raise RuntimeError("no tiene audio")
    except Exception as e:  # noqa: BLE001
        destino.unlink(missing_ok=True)
        raise HTTPException(400, f"No puedo leer el audio de '{archivo.filename}' ({e})")
    if p.get("cancion") and Path(p["cancion"]["ruta"]) != destino:
        Path(p["cancion"]["ruta"]).unlink(missing_ok=True)
    p["cancion"] = {"nombre": archivo.filename, "ruta": str(destino), "duracion": info["duracion"],
                    "url": f"/media/{pid}/{destino.name}"}
    p["analisis"] = {}
    guardar(p)
    return p


@app.delete("/api/proyectos/{pid}/cancion")
def quitar_cancion(pid: str):
    p = leer(pid)
    if p.get("cancion"):
        Path(p["cancion"]["ruta"]).unlink(missing_ok=True)
    p["cancion"] = None
    p["analisis"] = {}
    guardar(p)
    return p


# ---------------------------------------------------------------- el trabajo de verdad
def _analizar_cancion(p, progreso, forzar_transcripcion=False):
    """Beats + letra con tiempos de la canción entera (se cachea en el proyecto)."""
    can = p.get("cancion")
    if not can:
        p["analisis"].pop("cancion", None)
        return
    if "cancion" not in p["analisis"]:
        progreso(0.03, "Escuchando el ritmo de la canción")
        a = beats.analizar_cancion(can["ruta"])
        p["analisis"]["cancion"] = a
        guardar(p)
    if forzar_transcripcion or "palabras_cancion" not in p["analisis"]:
        wav = Path(can["ruta"]).parent / (Path(can["ruta"]).stem + "_16k.wav")
        media.extraer_wav(can["ruta"], wav)
        pista = " ".join(transcribe.lineas_de_letra(p.get("letra")))[:400]
        palabras = transcribe.transcribir(
            wav, p.get("modelo_voz", "small"), p.get("idioma", "es"), pista=pista, es_cancion=True,
            progreso=lambda x, m: progreso(0.05 + 0.75 * x, m))
        wav.unlink(missing_ok=True)
        p["analisis"]["palabras_cancion"] = palabras
        p["analisis"].pop("lineas_cancion", None)
        guardar(p)
    if "lineas_cancion" not in p["analisis"]:
        palabras = p["analisis"]["palabras_cancion"]
        if p.get("letra", "").strip():
            lineas = transcribe.alinear_letra(palabras, p["letra"])
        else:
            lineas = transcribe.lineas_desde_palabras(palabras)
        p["analisis"]["lineas_cancion"] = lineas
        guardar(p)


def _subtitulos_del_montaje(p, progreso):
    plan = p["plan"]
    if p.get("cancion"):
        return transcribe.lineas_en_tramo(p["analisis"].get("lineas_cancion", []),
                                          plan.get("inicio_cancion", 0), plan["duracion"])
    if not any(p["clips"][s["clip"]].get("tiene_audio") for s in plan["segmentos"]):
        return []
    wav = PROYECTOS / p["id"] / "montaje.wav"
    progreso(0.85, "Sacando el audio del montaje")
    media.audio_del_montaje(PROYECTOS / p["id"], plan, p["clips"], wav)
    palabras = transcribe.transcribir(wav, p.get("modelo_voz", "small"), p.get("idioma", "es"),
                                      progreso=lambda x, m: progreso(0.85 + 0.14 * x, m))
    wav.unlink(missing_ok=True)
    max_pal = 4 if plan["estilo"]["preset"] in ("tiktok", "palabra") else 7
    return transcribe.lineas_desde_palabras(palabras, max_pal)


def _preparar_plan(p, plan):
    plan["formato"] = p["formato"]
    plan["segmentos"] = montaje.construir_segmentos(plan, p["clips"], p["analisis"])
    if p.get("cancion"):
        plan["cancion"] = {"ruta": p["cancion"]["ruta"]}
    else:
        plan.pop("cancion", None)
    return plan


def trabajo_crear(pid, peticion_cambio, progreso):
    p = leer(pid)
    if not p["clips"]:
        raise RuntimeError("Añade al menos un vídeo")
    media.comprobar_ffmpeg()
    _analizar_cancion(p, progreso)
    progreso(0.82, "La IA está decidiendo el montaje" if os.environ.get("ANTHROPIC_API_KEY") else "Preparando montaje automático")
    plan_actual = p["plan"] if peticion_cambio else None
    peticion = peticion_cambio or p.get("peticion", "")
    plan, origen = planner.planificar(p["clips"], p["analisis"], peticion, p["formato"],
                                      float(p.get("duracion") or 0), plan_actual)
    anterior = p.get("plan") or {}
    plan = _preparar_plan(p, plan)
    p["plan"] = plan
    p["plan"]["origen"] = origen
    # Solo regeneramos subtítulos si cambia lo que suena (si no, se conservan tus ediciones)
    cambia_audio = (not p.get("subtitulos")
                    or anterior.get("inicio_cancion") != plan.get("inicio_cancion")
                    or anterior.get("duracion") != plan.get("duracion")
                    or (not p.get("cancion") and anterior.get("segmentos") != plan.get("segmentos")))
    if cambia_audio:
        p["subtitulos"] = _subtitulos_del_montaje(p, progreso)
    if peticion_cambio:
        p.setdefault("historial", []).append({"peticion": peticion_cambio, "explicacion": plan.get("explicacion", "")})
    guardar(p)
    return p


@app.post("/api/proyectos/{pid}/crear")
def crear(pid: str):
    leer(pid)
    return lanzar(trabajo_crear, pid, None)


@app.post("/api/proyectos/{pid}/cambiar")
def cambiar(pid: str, datos: dict):
    p = leer(pid)
    if not p.get("plan"):
        raise HTTPException(400, "Primero crea el vídeo")
    texto = (datos.get("peticion") or "").strip()
    if not texto:
        raise HTTPException(400, "Escribe qué quieres cambiar")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "Para pedir cambios con texto necesitas poner tu API key de Claude (botón Ajustes)")
    return lanzar(trabajo_crear, pid, texto)


def trabajo_remontar(pid, datos, progreso):
    p = leer(pid)
    plan = planner.validar({**p["plan"], **datos}, p["clips"], p["analisis"], base=p["plan"])
    anterior = p["plan"]
    plan = _preparar_plan(p, plan)
    plan["origen"] = anterior.get("origen")
    p["plan"] = plan
    if (anterior.get("inicio_cancion") != plan.get("inicio_cancion")
            or anterior.get("duracion") != plan.get("duracion") or not p.get("cancion")):
        p["subtitulos"] = _subtitulos_del_montaje(p, progreso)
    guardar(p)
    return p


@app.post("/api/proyectos/{pid}/remontar")
def remontar(pid: str, datos: dict):
    """Rehace el montaje con parámetros cambiados a mano (inicio de canción, duración, ritmo, encuadre…)."""
    p = leer(pid)
    if not p.get("plan"):
        raise HTTPException(400, "Primero crea el vídeo")
    permitidos = {k: v for k, v in datos.items()
                  if k in ("inicio_cancion", "duracion", "ritmo", "encuadre", "orden_clips", "semilla")}
    return lanzar(trabajo_remontar, pid, permitidos)


def trabajo_regenerar_subs(pid, progreso):
    p = leer(pid)
    if p.get("cancion"):
        _analizar_cancion(p, progreso, forzar_transcripcion=True)
    p["subtitulos"] = _subtitulos_del_montaje(p, progreso)
    guardar(p)
    return p


@app.post("/api/proyectos/{pid}/subtitulos/regenerar")
def regenerar_subs(pid: str):
    p = leer(pid)
    if not p.get("plan"):
        raise HTTPException(400, "Primero crea el vídeo")
    return lanzar(trabajo_regenerar_subs, pid)


def trabajo_render(pid, preview, progreso):
    p = leer(pid)
    d = PROYECTOS / pid
    plan = p["plan"]
    plan["formato"] = p["formato"]
    lineas = p["subtitulos"] if plan.get("subtitulos", True) else []
    ass = d / "subtitulos.ass"
    ass.write_text(subtitles.generar_ass(lineas, plan["estilo"], p["formato"]), encoding="utf-8")
    if preview:
        salida = d / "vista_previa.mp4"
    else:
        (d / "exportados").mkdir(exist_ok=True)
        salida = d / "exportados" / f"{_nombre_seguro(p['nombre'])}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    media.render(d, plan, p["clips"], ass, salida, preview=preview, progreso=progreso)
    rel = salida.relative_to(PROYECTOS).as_posix()
    url = f"/media/{rel}?v={int(time.time())}"
    p = leer(pid)
    if preview:
        p["ultimo_render"] = url
    else:
        p.setdefault("exportados", []).append({"url": url, "ruta": str(salida), "fecha": time.time()})
        # copia del .srt por si lo quieres subir aparte
        (salida.with_suffix(".srt")).write_text(_srt(lineas), encoding="utf-8")
    guardar(p)
    return {"url": url, "ruta": str(salida)}


def _srt(lineas):
    def t(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{t(l['inicio'])} --> {t(l['fin'])}\n{l['texto']}\n"
                     for i, l in enumerate(sorted(lineas, key=lambda l: l["inicio"]), 1))


@app.post("/api/proyectos/{pid}/render")
def render(pid: str, datos: dict):
    p = leer(pid)
    if not p.get("plan"):
        raise HTTPException(400, "Primero crea el vídeo")
    return lanzar(trabajo_render, pid, bool(datos.get("preview", True)))


@app.post("/api/proyectos/{pid}/abrir_carpeta")
def abrir_carpeta(pid: str):
    d = _dir(pid) / "exportados"
    d.mkdir(exist_ok=True)
    if os.name == "nt":
        os.startfile(d)  # noqa: S606 - abre el explorador de Windows
    else:
        subprocess.Popen(["xdg-open", str(d)])
    return {"ok": True}


@app.get("/")
def inicio():
    return FileResponse(RAIZ / "static" / "index.html")


app.mount("/static", StaticFiles(directory=RAIZ / "static"), name="static")
app.mount("/fonts", StaticFiles(directory=RAIZ / "fonts"), name="fonts")
