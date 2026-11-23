"""Convierte los parámetros del plan (ritmo de cortes, orden de clips...) en segmentos concretos."""
import random

MIN_SEG = 0.25


def _puntos_de_corte(plan, analisis, duracion):
    ritmo = plan.get("ritmo") or []
    cancion = analisis.get("cancion")
    if cancion and cancion.get("beats"):
        ini = float(plan.get("inicio_cancion", 0))
        beats = [b - ini for b in cancion["beats"] if ini < b < ini + duracion]
        cortes, contador, ultimo = [0.0], 0, 0.0
        for b in beats:
            contador += 1
            cada = 4
            for tramo in ritmo:
                if b <= float(tramo.get("hasta", 1e9)):
                    cada = int(tramo.get("cada_beats", 4) or 4)
                    break
            if contador >= max(1, cada) and b - ultimo >= MIN_SEG:
                cortes.append(b)
                ultimo, contador = b, 0
        if duracion - cortes[-1] < MIN_SEG and len(cortes) > 1:
            cortes.pop()
        return cortes + [duracion]

    # Sin canción: cortes cada N segundos si se pidió, si no un corte por clip
    cada_s = next((float(t["cada_segundos"]) for t in ritmo if t.get("cada_segundos")), None)
    if cada_s:
        n = max(1, int(duracion // cada_s))
        return [round(i * cada_s, 3) for i in range(n)] + [duracion]
    return None


def construir_segmentos(plan, clips, analisis):
    orden = [i for i in plan.get("orden_clips") or range(len(clips)) if 0 <= i < len(clips)]
    if not orden:
        orden = list(range(len(clips)))
    rangos = {int(r["clip"]): r for r in plan.get("rangos_clips") or [] if "clip" in r}

    def rango(i):
        r = rangos.get(i, {})
        a = max(0.0, float(r.get("desde", 0)))
        b = min(clips[i]["duracion"], float(r.get("hasta", clips[i]["duracion"])))
        return (a, b) if b - a > 0.2 else (0.0, clips[i]["duracion"])

    duracion = float(plan.get("duracion") or 0)
    if not duracion:
        cancion = analisis.get("cancion")
        duracion = (cancion["duracion"] - float(plan.get("inicio_cancion", 0))) if cancion \
            else sum(rango(i)[1] - rango(i)[0] for i in orden)
    duracion = max(1.0, duracion)
    plan["duracion"] = round(duracion, 3)

    cortes = _puntos_de_corte(plan, analisis, duracion)
    if cortes is None:  # clips enteros, uno detrás de otro
        segs, t = [], 0.0
        while t < duracion - 0.05:
            for i in orden:
                a, b = rango(i)
                d = min(b - a, duracion - t)
                if d <= 0.05:
                    break
                segs.append({"clip": i, "entrada": round(a, 3), "inicio": round(t, 3), "fin": round(t + d, 3)})
                t += d
            if not segs:
                break
        return segs

    rnd = random.Random(plan.get("semilla", 7))
    pos = {i: rango(i)[0] for i in orden}
    segs = []
    k = 0
    for a, b in zip(cortes[:-1], cortes[1:]):
        d = b - a
        # siguiente clip en orden que tenga metraje suficiente
        elegido, vel = None, 1.0
        for intento in range(len(orden)):
            i = orden[(k + intento) % len(orden)]
            ra, rb = rango(i)
            if rb - ra >= d:
                elegido = i
                k = k + intento + 1
                break
        if elegido is None:  # ningún clip es tan largo: ralentizamos el más largo
            elegido = max(orden, key=lambda i: rango(i)[1] - rango(i)[0])
            ra, rb = rango(elegido)
            vel = max(0.5, (rb - ra) / d)
            k += 1
        ra, rb = rango(elegido)
        necesario = d * vel
        if pos[elegido] + necesario > rb:
            pos[elegido] = ra
        entrada = pos[elegido]
        # avanzamos y saltamos un poco para no repetir siempre el mismo trozo
        pos[elegido] += necesario + rnd.uniform(0, 0.4) * necesario
        seg = {"clip": elegido, "entrada": round(entrada, 3), "inicio": round(a, 3), "fin": round(b, 3)}
        if vel != 1.0:
            seg["velocidad"] = round(vel, 3)
        segs.append(seg)
    return segs
