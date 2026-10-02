# -*- coding: utf-8 -*-
"""
Vuelve a bajar los videos que quedaron como fragmento DASH en vez de archivo
completo.

Que paso: Instagram sirve el video por DASH, o sea que el reproductor pide
TROZOS con rango de bytes (`bytestart` / `byteend`), y esas son las URLs que ve
la Performance API. Bajarlas tal cual deja un fragmento que empieza en la caja
`moof`, sin la cabecera ftyp/moov, y practicamente ningun reproductor lo abre.
En la corrida del 28/08/2026 quedaron asi 477 de 497 videos. Quitando esos dos
parametros el CDN devuelve el archivo entero.

El script solo toca los archivos que de verdad estan rotos: lee la cabecera de
cada .mp4 y deja en paz los que ya empiezan en `ftyp`.

OJO con el reloj: las URLs del CDN caducan (token `oe=`). Las que ya vencieron
no se pueden reparar desde aqui, hay que volver a scrapear esos posts; el
script las lista en videos_caducados.csv.

Uso:
    python ig/reparar_videos.py --dry-run
    python ig/reparar_videos.py
    python ig/reparar_videos.py resultados_ig/global_20260828_163758.json
"""
import os, re, sys, csv, json, glob, time

try:
    import requests
except ImportError:
    sys.exit("Falta 'requests'. Instala con: pip install -r requirements.txt")

RESULTADOS_DIR = "resultados_ig"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PAUSA = 0.4
DRY = "--dry-run" in sys.argv


def limpiar_url_video(u):
    if not u:
        return u
    u = re.sub(r"[?&]bytestart=\d+", "", u)
    u = re.sub(r"[?&]byteend=\d+", "", u)
    if "?" not in u and "&" in u:
        u = u.replace("&", "?", 1)
    return u


def ruta_real(local):
    """
    `video_local` se guarda relativo a resultados_ig ("media/<usuario>/x.mp4"),
    pero el script se corre desde la raiz del repo. Se resuelven las dos formas.
    """
    if not local:
        return local
    if os.path.exists(local):
        return local
    alt = os.path.join(RESULTADOS_DIR, local)
    return alt if os.path.exists(alt) else local


def cabecera(ruta):
    """'completo' si empieza en ftyp, 'fragmento' si empieza en moof."""
    try:
        with open(ruta, "rb") as f:
            h = f.read(12)
    except OSError:
        return "ausente"
    if h[4:8] == b"ftyp":
        return "completo"
    if h[4:8] == b"moof":
        return "fragmento"
    return "raro"


def caducada(url):
    m = re.search(r"[?&]oe=([0-9A-Fa-f]{6,10})", url or "")
    if not m:
        return False
    try:
        return int(m.group(1), 16) < time.time()
    except ValueError:
        return False


def main():
    libres = [a for a in sys.argv[1:] if not a.startswith("-")]
    if libres:
        ruta_global = libres[0]
    else:
        cand = [f for f in glob.glob(os.path.join(RESULTADOS_DIR, "global_2*.json"))
                if "anonimo" not in os.path.basename(f)]
        if not cand:
            sys.exit("No encuentro ningun global_*.json en %s" % RESULTADOS_DIR)
        ruta_global = sorted(cand)[-1]

    print("Leyendo: %s\n" % ruta_global)
    datos = json.load(open(ruta_global, encoding="utf-8")).get("resultados", [])

    pendientes, vencidos = [], []
    resumen = {"completo": 0, "ausente": 0, "raro": 0}
    for r in datos:
        for p in (r.get("posts_data") or []):
            local, url = p.get("video_local"), p.get("video_url")
            if not local or not url:
                continue
            local = ruta_real(local)
            estado = cabecera(local)
            if estado != "fragmento":
                resumen[estado if estado in resumen else "raro"] += 1
                continue
            if caducada(url):
                vencidos.append((r.get("id"), r.get("usuario"), local, p.get("url")))
            else:
                pendientes.append((local, limpiar_url_video(url)))

    print("Videos ya completos      : %d" % resumen["completo"])
    print("Fragmentos reparables    : %d" % len(pendientes))
    print("Fragmentos con URL vencida: %d  (hay que volver a scrapear esos posts)"
          % len(vencidos))
    if resumen["ausente"] or resumen["raro"]:
        print("Otros (ausente/raro)     : %d" % (resumen["ausente"] + resumen["raro"]))

    if vencidos and not DRY:
        ruta = os.path.join(RESULTADOS_DIR, "videos_caducados.csv")
        with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "usuario", "archivo_roto", "url_del_post"])
            w.writerows(vencidos)
        print("\nLista de vencidos en: %s" % ruta)

    if DRY:
        print("\n(--dry-run: no se descargo nada)")
        return 0

    ok = fallos = 0
    for n, (destino, url) in enumerate(pendientes, 1):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": UA})
            r.raise_for_status()
            tmp = destino + ".nuevo"
            with open(tmp, "wb") as f:
                f.write(r.content)
            if cabecera(tmp) == "completo":
                os.replace(tmp, destino)
                ok += 1
            else:
                os.remove(tmp)
                fallos += 1
                print("  [%d/%d] %s sigue sin ser completo" % (n, len(pendientes),
                                                               os.path.basename(destino)))
        except Exception as e:
            fallos += 1
            print("  [%d/%d] %s -> %s" % (n, len(pendientes),
                                          os.path.basename(destino), str(e)[:60]))
        if n % 25 == 0:
            print("  ... %d/%d" % (n, len(pendientes)))
        time.sleep(PAUSA)

    print("\n=== RESULTADO ===")
    print("  reparados : %d" % ok)
    print("  fallidos  : %d" % fallos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
