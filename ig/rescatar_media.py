# -*- coding: utf-8 -*-
"""
Rescate de imagenes y videos de una corrida YA hecha.

Por que existe: las URLs del CDN de Instagram llevan un token `oe=` con fecha
de caducidad. Las de la corrida del 27/08/2026 vencian todas el 1 de septiembre
de 2026, y esa corrida no descargo ningun binario, solo guardo URLs. Este
script recorre el HTML que si quedo guardado (resultados_ig/debug_dom/*.html y
perfil_*.html), saca de ahi og:image / og:video y baja los archivos antes de
que expiren.

A partir del arreglo del 28/08/2026 el scraper ya descarga el media en el
momento (DESCARGAR_MEDIA), asi que esto solo hace falta para corridas viejas.

Uso:
    python ig/rescatar_media.py                 # baja todo lo que falte
    python ig/rescatar_media.py --dry-run       # solo dice que haria
    python ig/rescatar_media.py --solo-perfiles # solo fotos de perfil
"""
import os, re, sys, csv, json, time, glob, html as H

try:
    import requests
except ImportError:
    sys.exit("Falta 'requests'. Instala con: pip install -r requirements.txt")

RESULTADOS_DIR = "resultados_ig"
MEDIA_DIR = os.path.join(RESULTADOS_DIR, "media")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PAUSA = 0.4          # cortesia con el CDN
REINTENTOS = 2

DRY = "--dry-run" in sys.argv
SOLO_PERFILES = "--solo-perfiles" in sys.argv

# De donde se LEE el HTML. Por defecto resultados_ig, pero si la corrida ya se
# archivo se le puede pasar la carpeta:
#     python ig/rescatar_media.py resultados_ig/corrida_20260827
# Lo descargado siempre va a resultados_ig/media, sin importar la fuente.
_libres = [a for a in sys.argv[1:] if not a.startswith("-")]
FUENTE_DIR = _libres[0] if _libres else RESULTADOS_DIR


def meta(html, prop):
    m = re.search(r'<meta property="%s" content="([^"]*)"' % re.escape(prop), html)
    return H.unescape(m.group(1)) if m else None


RE_VIDEO = re.compile(r'https?://[^"\'\\\s]+(?:/o1/v/t16/|\.mp4)[^"\'\\\s]*')


def es_post_de_video(html):
    return bool(re.search(r"<video[\s>]", html) or
                re.search(r'og:type" content="video', html))


def url_de_video(html):
    """
    Busca una URL de video aprovechable dentro del HTML guardado.

    Casi nunca hay. Instagram reproduce con MediaSource: el <video> apunta a un
    "blob:" que solo existia en aquella pestana, y `video_dash_manifest` viene
    en null. De los 90 posts de video de la corrida del 27/08/2026, solo 5
    dejaron una URL utilizable. Los otros 85 solo se recuperan volviendo a
    scrapear, y para eso ya esta el arreglo en scrappingData_ig.py.
    """
    directo = re.search(r'<meta property="og:video(?::secure_url)?" content="([^"]+)"', html)
    if directo:
        return H.unescape(directo.group(1))
    encontradas = RE_VIDEO.findall(html)
    if not encontradas:
        return None
    return H.unescape(max(encontradas, key=len))


def caduca_en(url):
    """Lee el token oe= de la URL y devuelve el epoch de expiracion, o None."""
    m = re.search(r"[?&]oe=([0-9A-Fa-f]{6,10})", url or "")
    try:
        return int(m.group(1), 16) if m else None
    except ValueError:
        return None


def bajar(url, destino):
    if not url:
        return "sin_url"
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return "ya_estaba"
    if DRY:
        return "bajaria"
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    for intento in range(REINTENTOS + 1):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": UA})
            if r.status_code == 403:
                return "caducada"          # el token oe= ya vencio
            r.raise_for_status()
            with open(destino, "wb") as f:
                f.write(r.content)
            return "ok"
        except Exception as e:
            if intento == REINTENTOS:
                return "error: %s" % str(e)[:60]
            time.sleep(1.5 * (intento + 1))


def mapa_shortcode_a_paciente():
    """shortcode -> (id, usuario), leido del global mas reciente."""
    globales = sorted(glob.glob(os.path.join(FUENTE_DIR, "global_2*.json")))
    globales = [g for g in globales if "anonimo" not in os.path.basename(g)]
    if not globales:
        return {}
    datos = json.load(open(globales[-1], encoding="utf-8")).get("resultados", [])
    mapa = {}
    for r in datos:
        for p in (r.get("posts_data") or []):
            m = re.search(r"/(?:p|reel)/([^/]+)/", p.get("url") or "")
            if m:
                mapa[m.group(1)] = (r.get("id"), r.get("usuario"))
    print("Mapa de posts: %d shortcodes desde %s" % (len(mapa), os.path.basename(globales[-1])))
    return mapa


def main():
    if not os.path.isdir(FUENTE_DIR):
        sys.exit("No encuentro %s. Corre esto desde la raiz del repo." % FUENTE_DIR)
    print("Leyendo HTML de : %s" % os.path.abspath(FUENTE_DIR))
    print("Guardando en    : %s\n" % os.path.abspath(MEDIA_DIR))

    resumen = {}
    def anota(k):
        resumen[k] = resumen.get(k, 0) + 1

    ahora = int(time.time())
    proximos_a_vencer = []

    # ---- fotos de perfil ---------------------------------------------------
    for f in sorted(glob.glob(os.path.join(FUENTE_DIR, "perfil_*.html"))):
        m = re.match(r"perfil_(.+)_(\d{6})\.html$", os.path.basename(f))
        if not m:
            continue
        usuario = m.group(1)
        url = meta(open(f, encoding="utf-8", errors="ignore").read(), "og:image")
        exp = caduca_en(url or "")
        if exp and exp - ahora < 7 * 86400:
            proximos_a_vencer.append(exp)
        r = bajar(url, os.path.join(MEDIA_DIR, "_perfiles", "%s.jpg" % usuario))
        anota("perfil:" + r.split(":")[0])
        if r == "ok":
            time.sleep(PAUSA)          # solo se pausa cuando de verdad se descargo

    # ---- media de cada post ------------------------------------------------
    if not SOLO_PERFILES:
        mapa = mapa_shortcode_a_paciente()
        sin_video = []
        for f in sorted(glob.glob(os.path.join(FUENTE_DIR, "debug_dom", "*.html"))):
            sc = os.path.basename(f).rsplit("_", 1)[0]
            html = open(f, encoding="utf-8", errors="ignore").read()
            pid, usuario = mapa.get(sc, (None, "_sin_paciente"))
            carpeta = os.path.join(MEDIA_DIR, re.sub(r'[\\/*?:"<>|\s]', "_", usuario or "_sin_paciente"))

            # 1) la imagen. En un post de video esto es el frame de portada,
            #    no el video: se guarda igual porque sirve de miniatura.
            img = meta(html, "og:image")
            exp = caduca_en(img or "")
            if exp and exp - ahora < 7 * 86400:
                proximos_a_vencer.append(exp)
            r = bajar(img, os.path.join(carpeta, "%s.jpg" % sc))
            anota("imagen:" + r.split(":")[0])
            if r.startswith("error") or r == "caducada":
                print("  %s (imagen) -> %s" % (sc, r))
            if r == "ok":
                time.sleep(PAUSA)

            # 2) el video, si el HTML guardo alguna URL utilizable.
            if es_post_de_video(html):
                vid = url_de_video(html)
                if not vid:
                    anota("video:sin_url_en_html")
                    sin_video.append((pid or "", usuario or "", sc))
                    continue
                exp = caduca_en(vid)
                if exp and exp - ahora < 7 * 86400:
                    proximos_a_vencer.append(exp)
                r = bajar(vid, os.path.join(carpeta, "%s.mp4" % sc))
                anota("video:" + r.split(":")[0])
                if r.startswith("error") or r == "caducada":
                    print("  %s (video) -> %s" % (sc, r))
                if r == "ok":
                    time.sleep(PAUSA)

        if sin_video and not DRY:
            ruta = os.path.join(RESULTADOS_DIR, "videos_no_recuperables.csv")
            with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["id", "usuario", "shortcode", "url_del_post", "motivo"])
                for pid, usuario, sc in sin_video:
                    w.writerow([pid, usuario, sc,
                                "https://www.instagram.com/p/%s/" % sc,
                                "el HTML guardado no trae URL de video (MediaSource/blob)"])
            print("\n  %d videos NO se pueden rescatar del HTML." % len(sin_video))
            print("  Lista en: %s" % ruta)
            print("  Esos solo vuelven con la corrida nueva de scrappingData_ig.py.")

    print("\n=== RESUMEN ===")
    for k in sorted(resumen):
        print("  %-20s %d" % (k, resumen[k]))
    if proximos_a_vencer:
        falta = (min(proximos_a_vencer) - ahora) / 3600.0
        print("\n  El token mas proximo a vencer caduca en %.1f horas." % falta)
    print("  Archivos en: %s" % os.path.abspath(MEDIA_DIR))
    if DRY:
        print("  (--dry-run: no se escribio nada)")


if __name__ == "__main__":
    main()
