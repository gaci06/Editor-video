"""Todo lo que toca FFmpeg: analizar ficheros, extraer audio, miniaturas y render final."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

FORMATOS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
FPS = 30

# En Windows evitamos que se abra una ventana negra por cada llamada a FFmpeg
_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def comprobar_ffmpeg():
    falta = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if falta:
        raise RuntimeError(
            "No encuentro " + " ni ".join(falta) + ". Ejecuta instalar.bat o instala FFmpeg "
            "(winget install Gyan.FFmpeg) y reinicia el ordenador."
        )


def _run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=_FLAGS)
    if r.returncode != 0:
        cola = "\n".join(r.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"FFmpeg falló:\n{cola}")
    return r


def analizar(ruta):
    """Duración, tamaño y si tiene audio."""
    r = _run(["ffprobe", "-v", "error", "-print_format", "json",
              "-show_format", "-show_streams", str(ruta)])
    info = json.loads(r.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"].get("duration") or 0)
    datos = {"duracion": round(dur, 3), "tiene_audio": audio is not None}
    if video:
        w, h = int(video["width"]), int(video["height"])
        rot = 0
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = abs(int(float(sd["rotation"])))
        rot = rot or abs(int(video.get("tags", {}).get("rotate", 0) or 0))
        if rot in (90, 270):  # vídeos de móvil grabados en vertical
            w, h = h, w
        datos.update(ancho=w, alto=h)
    return datos


def miniatura(ruta, destino, segundo=0.5):
    _run(["ffmpeg", "-y", "-v", "error", "-ss", str(segundo), "-i", str(ruta),
          "-frames:v", "1", "-vf", "scale=240:-2", str(destino)])


def cargar_audio(ruta, sr=22050):
    """Devuelve el audio en mono como array float32 (usa FFmpeg, sin librerías extra)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(ruta), "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True, creationflags=_FLAGS)
    if r.returncode != 0:
        raise RuntimeError("No pude leer el audio: " + r.stderr.decode(errors="replace")[-400:])
    return np.frombuffer(r.stdout, dtype=np.float32), sr


def extraer_wav(ruta, destino, inicio=0.0, duracion=None):
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{inicio:.3f}", "-i", str(ruta)]
    if duracion:
        cmd += ["-t", f"{duracion:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", str(destino)]
    _run(cmd)


def _filtro_encuadre(w, h, encuadre):
    if encuadre == "ajustar":  # todo el vídeo visible con fondo desenfocado
        return (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},boxblur=20:2[fondo];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[frente];"
                f"[fondo][frente]overlay=(W-w)/2:(H-h)/2")
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def render(proyecto_dir, plan, clips, ass_path, salida, preview=False, progreso=None):
    """Monta el vídeo final.

    1) corta cada segmento a un fichero intermedio con el mismo formato
    2) los une sin recodificar
    3) quema subtítulos y pone la música
    """
    comprobar_ffmpeg()
    proyecto_dir = Path(proyecto_dir)
    tmp = proyecto_dir / "tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(exist_ok=True)

    w, h = FORMATOS.get(plan.get("formato", "9:16"), FORMATOS["9:16"])
    if preview:
        w, h = (w // 2) // 2 * 2, (h // 2) // 2 * 2
    calidad = ["-preset", "ultrafast", "-crf", "30"] if preview else ["-preset", "medium", "-crf", "19"]
    encuadre = plan.get("encuadre", "llenar")
    segmentos = plan["segmentos"]
    usar_audio_clips = not plan.get("cancion")
    total = len(segmentos) + 1

    lista = []
    for i, seg in enumerate(segmentos):
        clip = clips[seg["clip"]]
        dur = max(0.05, seg["fin"] - seg["inicio"])
        dest = tmp / f"seg_{i:04d}.mp4"
        vf = _filtro_encuadre(w, h, encuadre) + f",setsar=1,fps={FPS},format=yuv420p"
        vel = float(seg.get("velocidad", 1) or 1)
        if vel != 1:
            vf += f",setpts=PTS/{vel}"
        vf += f",tpad=stop_mode=clone:stop_duration={dur:.3f}"  # nunca más corto de lo previsto
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{seg['entrada']:.3f}",
               "-t", f"{dur * vel:.3f}", "-i", clip["ruta"]]
        if usar_audio_clips and not clip.get("tiene_audio"):
            cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]"]
        if usar_audio_clips:
            if clip.get("tiene_audio"):
                af = (f"atempo={vel}" if vel != 1 and 0.5 <= vel <= 2 else "anull") + ",apad"
                cmd += ["-map", "0:a:0", "-af", af + ",aresample=48000", "-ac", "2"]
            else:
                cmd += ["-map", "1:a"]
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", *calidad, "-r", str(FPS), str(dest)]
        _run(cmd)
        lista.append(f"file '{dest.name}'")
        if progreso:
            progreso((i + 1) / total, f"Montando clip {i + 1} de {len(segmentos)}")

    (tmp / "lista.txt").write_text("\n".join(lista), encoding="utf-8")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
          "-c", "copy", "unido.mp4"], cwd=tmp)

    if progreso:
        progreso((total - 0.5) / total, "Añadiendo subtítulos y música")

    duracion = sum(s["fin"] - s["inicio"] for s in segmentos)
    # Rutas relativas a propósito: el filtro de subtítulos se lleva fatal con "C:\"
    fonts_rel = os.path.relpath(Path(__file__).resolve().parent.parent / "fonts", tmp).replace("\\", "/")
    ass_rel = os.path.relpath(ass_path, tmp).replace("\\", "/")
    vf = f"subtitles='{ass_rel}':fontsdir='{fonts_rel}'"
    if preview:
        vf += f",scale={w}:{h}"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", "unido.mp4"]
    cancion = plan.get("cancion")
    if cancion:
        ini = float(plan.get("inicio_cancion", 0))
        fade = min(1.5, duracion / 4)
        cmd += ["-ss", f"{ini:.3f}", "-t", f"{duracion:.3f}", "-i", cancion["ruta"],
                "-map", "0:v", "-map", "1:a",
                "-af", f"afade=t=out:st={duracion - fade:.3f}:d={fade:.3f}"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a?"]
    cmd += ["-vf", vf, "-c:v", "libx264", *calidad, "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{duracion:.3f}", os.path.relpath(salida, tmp)]
    _run(cmd, cwd=tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    if progreso:
        progreso(1.0, "Listo")
    return salida


def audio_del_montaje(proyecto_dir, plan, clips, destino):
    """Audio (16 kHz mono) tal y como sonará en el montaje sin canción, para transcribirlo."""
    tmp = Path(proyecto_dir) / "tmp_audio"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    lista = []
    for i, seg in enumerate(plan["segmentos"]):
        clip = clips[seg["clip"]]
        dur = seg["fin"] - seg["inicio"]
        dest = tmp / f"a_{i:04d}.wav"
        if clip.get("tiene_audio"):
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{seg['entrada']:.3f}", "-t", f"{dur:.3f}",
                  "-i", clip["ruta"], "-vn", "-ac", "1", "-ar", "16000", "-af", "apad",
                  "-t", f"{dur:.3f}", str(dest)])
        else:
            _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                  "-t", f"{dur:.3f}", str(dest)])
        lista.append(f"file '{dest.name}'")
    (tmp / "lista.txt").write_text("\n".join(lista), encoding="utf-8")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
          "-c", "copy", os.path.relpath(destino, tmp)], cwd=tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return destino
