"""Arranca el editor y abre el navegador."""
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

PUERTO = 8765


def libre(puerto):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


if __name__ == "__main__":
    if not libre(PUERTO):
        print("El editor ya está abierto. Abriendo el navegador…")
        webbrowser.open(f"http://127.0.0.1:{PUERTO}")
        sys.exit(0)
    url = f"http://127.0.0.1:{PUERTO}"
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    print(f"Editor de vídeo funcionando en {url}  (cierra esta ventana para apagarlo)")
    uvicorn.run("app.server:app", host="127.0.0.1", port=PUERTO, log_level="warning")
