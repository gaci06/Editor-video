# Editor de vídeo para Reels y TikTok

Le das vídeos, una canción (opcional) y una idea en texto. El editor:

1. detecta el ritmo de la canción (BPM y beats) y corta los clips al compás;
2. saca los subtítulos automáticamente (Whisper, en tu ordenador) y, si pegas la letra, la sincroniza con lo que se canta;
3. con la IA de Claude decide el tramo de la canción, el ritmo de cortes y el estilo de los subtítulos según lo que pidas;
4. te deja **editar todo a mano**: texto y tiempos de cada subtítulo, estilo, qué trozo de cada clip sale y cuánto dura;
5. exporta el MP4 final (más un `.srt`) en la carpeta `proyectos/<id>/exportados`.

## Instalación (Windows)

1. Doble clic en **`instalar.bat`**. Instala Python y FFmpeg si faltan (con `winget`) y las librerías.
   Si te dice que cierres y lo vuelvas a abrir, hazlo; Windows necesita recargar el PATH.
2. Doble clic en **`iniciar.bat`**. Se abre el navegador en `http://127.0.0.1:8765`.
3. (Opcional) En **Ajustes**, pega tu API key de Claude. Sin ella todo funciona, pero el montaje es automático
   y no puedes pedir cambios con texto.

La primera vez que generes subtítulos se descarga el modelo de voz (de 150 MB a 1,5 GB según la precisión).

## Cómo se usa

1. **Nuevo vídeo** → arrastra los clips → añade la canción → pega la letra (muy recomendable con canciones).
2. Elige formato (9:16, 16:9, 1:1, 4:5) y duración (0 = automática).
3. Escribe la idea: *«20 segundos con el estribillo, cortes cada beat cuando sube, palabra a palabra en amarillo»*.
4. **Crear vídeo** → se genera una vista previa a media resolución.
5. Retoca: estilo, subtítulos, trozos de la línea de tiempo, o escribe cambios en «Pide cambios».
6. **Exportar en calidad final**.

## Cómo está hecho

| Parte | Archivo | Qué hace |
|---|---|---|
| Servidor | `app/server.py` | FastAPI local, proyectos en `proyectos/<id>/proyecto.json`, trabajos en segundo plano |
| Ritmo | `app/beats.py` | Envolvente de ataques + autocorrelación (tempo) + programación dinámica (beats). Solo numpy |
| Voz | `app/transcribe.py` | faster-whisper en CPU (int8) y alineación de la letra con `difflib` |
| IA | `app/planner.py` | Claude devuelve un plan en JSON; se valida antes de usarlo |
| Montaje | `app/montaje.py` | Convierte el plan en segmentos (clip, segundo de entrada, inicio, fin) |
| Subtítulos | `app/subtitles.py` | Genera `.ass` con 4 estilos: tiktok, karaoke, palabra, frase |
| Render | `app/media.py` | FFmpeg: corta y encuadra cada trozo, une, quema subtítulos y pone la música |
| Interfaz | `static/` | HTML + CSS + JS sin frameworks |

La IA **no edita el vídeo**: solo decide parámetros. Así el resultado es reproducible y lo puedes retocar a mano.

## Límites conocidos

- Sin GPU, transcribir es la parte lenta. No está medido en vuestros portátiles: prueba primero con *small* y baja a *base* si tarda demasiado.
- Whisper entiende mal la voz cantada con mucha música; por eso pegar la letra mejora tanto el resultado.
- Si cambias el inicio de la canción o la duración, los subtítulos se regeneran y se pierden las ediciones de texto.
- Las fuentes incluidas (Anton, Archivo Black, Poppins) tienen licencia SIL OFL (ver `fonts/OFL.txt`).
