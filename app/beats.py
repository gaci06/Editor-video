"""Detección de tempo, beats y energía de una canción usando solo numpy.

Método: envolvente de ataques (spectral flux) -> tempo por autocorrelación ->
beats por programación dinámica (Ellis, 2007, "Beat Tracking by Dynamic Programming").
"""
import numpy as np

from .media import cargar_audio

SR = 22050
HOP = 512
NFFT = 2048


def _envolvente(y):
    if len(y) < NFFT:
        y = np.pad(y, (0, NFFT - len(y)))
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    ventana = np.hanning(NFFT).astype(np.float32)
    espectro = np.abs(np.fft.rfft(y[idx] * ventana, axis=1))
    # Agrupamos en ~64 bandas logarítmicas para parecernos a un mel
    bins = espectro.shape[1]
    bordes = np.unique(np.geomspace(2, bins, 65).astype(int))
    bandas = np.stack([espectro[:, a:b].mean(axis=1) for a, b in zip(bordes[:-1], bordes[1:])], axis=1)
    log = np.log1p(100 * bandas)
    flux = np.maximum(0, np.diff(log, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    # quitar tendencia lenta y normalizar
    k = int(SR / HOP)  # ~1 s
    suave = np.convolve(flux, np.ones(k) / k, mode="same")
    env = np.maximum(0, flux - suave)
    return env / (env.std() + 1e-9)


def _tempo(env):
    fps = SR / HOP
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lag_min, lag_max = int(fps * 60 / 200), int(fps * 60 / 60)
    lags = np.arange(lag_min, min(lag_max, len(ac) - 1))
    if len(lags) == 0:
        return 120.0
    bpm = 60 * fps / lags
    peso = np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)  # preferencia suave por ~120 BPM
    i = int(np.argmax(ac[lags] * peso))
    mejor = float(lags[i])
    if 0 < i < len(lags) - 1:  # interpolación parabólica para afinar el BPM
        a, b, c = ac[lags[i - 1]], ac[lags[i]], ac[lags[i + 1]]
        den = a - 2 * b + c
        if den != 0:
            mejor += 0.5 * (a - c) / den
    return float(60 * fps / mejor)


def _beats(env, bpm, alpha=100.0):
    fps = SR / HOP
    periodo = 60 * fps / bpm
    n = len(env)
    score = env.astype(np.float64).copy()
    previo = np.full(n, -1)
    ventana = np.arange(-int(round(2 * periodo)), -int(round(periodo / 2)) + 1)
    coste = -alpha * np.log(-ventana / periodo) ** 2
    for t in range(n):
        cand = t + ventana
        ok = cand >= 0
        if not ok.any():
            continue
        valores = score[cand[ok]] + coste[ok]
        j = np.argmax(valores)
        score[t] = env[t] + valores[j]
        previo[t] = cand[ok][j]
    # último beat: máximo entre los frames finales con score alto
    cola = score[-int(2 * periodo):] if n > 2 * periodo else score
    t = n - len(cola) + int(np.argmax(cola))
    beats = []
    while t >= 0:
        beats.append(t)
        t = previo[t]
    # +NFFT/2: cada frame está centrado en la mitad de su ventana
    return (np.array(beats[::-1]) * HOP + NFFT / 2) / SR


def analizar_cancion(ruta):
    y, sr = cargar_audio(ruta, SR)
    duracion = len(y) / sr
    env = _envolvente(y)
    bpm = _tempo(env)
    beats = _beats(env, bpm)
    # Energía por segundo (0-1), útil para que la IA encuentre estribillos y subidas
    seg = int(sr)
    n = max(1, len(y) // seg)
    rms = np.sqrt(np.mean(y[: n * seg].reshape(n, seg) ** 2, axis=1))
    energia = (rms / (rms.max() + 1e-9)).round(2).tolist()
    return {
        "duracion": round(duracion, 3),
        "bpm": round(bpm, 1),
        "beats": [round(float(b), 3) for b in beats],
        "energia": energia,
    }
