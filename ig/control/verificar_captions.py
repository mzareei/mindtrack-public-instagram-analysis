# -*- coding: utf-8 -*-
"""
Etapa 3: buscar la edad en los captions de quien paso el triaje sin edad en la bio.

Abre hasta MAX_POSTS posts del perfil, lee caption y fecha con las funciones
del scraper de siempre, y busca formulas en primera persona ("cumplo 17",
"mis 18", "ya tengo 16 años"), ajustando por la fecha del post. NO baja media ni
expande comentarios: si la persona no se aprueba, no se le extrae nada mas.

Uso:
    python ig/control/verificar_captions.py [--csv ig/control/candidatos_pendientes_formato.csv]
                                             [--reanudar] [--limite N] [--dormir-al-limite]
"""

import csv, json, os, random, sys, time
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))
import inferir_edad as ie
from util import id_control

MAX_POSTS = 12
PAUSA_POST = (3.0, 6.0)
PAUSA_PERFIL = (8.0, 14.0)
LIMITE_ANOMALIAS = 6
SIESTA_LIMITE_S = 45 * 60

SALIDA = os.path.join(DIR, "captions.csv")
CKPT = os.path.join(DIR, "captions_en_curso.json")
APROBADOS = os.path.join(DIR, "candidatos_aprobados_formato.csv")
MAESTRO = os.path.join(DIR, "controles_evidencia.csv")

_JS_LINKS = ("return Array.from(document.querySelectorAll(\"a[href*='/p/'], a[href*='/reel/']\"))"
             "            .map(function(a){return a.href.split('?')[0];});")


def leer_captions(driver, ig, usuario, max_posts=MAX_POSTS):
    driver.get("https://www.instagram.com/%s/" % usuario)
    time.sleep(3.5)
    for _ in range(2):
        driver.execute_script("window.scrollBy(0, 1400);")
        time.sleep(1.5)
    vistos, links = set(), []
    for u in driver.execute_script(_JS_LINKS) or []:
        if u not in vistos:
            vistos.add(u)
            links.append(u)
    salida = []
    for link in links[:max_posts]:
        try:
            driver.get(link)
            time.sleep(random.uniform(*PAUSA_POST))
            cap = ig.extraer_caption_post(driver) or {}
            # Solo posts de la propia persona: un post ajeno donde la etiquetaron
            # no dice nada de su edad.
            # El dueño se saca de la URL, NO de username_post: ese campo salia
            # corrupto en 1,447 de 1,448 posts (la regex esperaba la fecha en
            # español y Instagram la sirve en inglés), asi que descartaba
            # justo los posts CON caption, que son los unicos donde puede
            # haber una edad. Arreglado el 05/09/2026 en las dos puntas.
            autor = (ig._dueno_de_url(link) or "").strip().lower()
            if autor and autor != usuario.lower():
                continue
            f = ig.obtener_fecha_post(driver, url_post=link)
            salida.append((cap.get("caption") or "", f.isoformat() if f else None))
        except Exception as e:
            print("     aviso %s: %s" % (link[-14:], e))
    return salida


def _fusionar_aprobados(nuevos):
    """Añade a candidatos_aprobados_formato.csv sin duplicar."""
    existentes = set()
    filas = []
    if os.path.exists(APROBADOS):
        for r in csv.DictReader(open(APROBADOS, encoding="utf-8-sig")):
            if r.get("instagram"):
                existentes.add(r["instagram"].lower())
                filas.append(r["instagram"])
    for u in nuevos:
        if u.lower() not in existentes:
            filas.append(u)
            existentes.add(u.lower())
    hoy = datetime.now().strftime("%m/%d/%Y")
    with open(APROBADOS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
        for u in filas:
            w.writerow([id_control(u), "1/1/2010", hoy, u, "", "", ""])
    return len(filas)


def escribir_maestro(log=print):
    """controles_evidencia.csv: un renglon por control aprobado, de cualquier
    etapa, con la evidencia que lo sostiene. Es la tabla del articulo."""
    filas = {}
    ruta_t = os.path.join(DIR, "triaje.csv")
    if os.path.exists(ruta_t):
        for r in csv.DictReader(open(ruta_t, encoding="utf-8-sig")):
            # formato viejo (aprobado si/no) -> aprobado_bio
            if "veredicto" not in r and r.get("aprobado") == "si":
                r = dict(r, veredicto="aprobado_bio", banda="", evidencia="bio")
            if str(r.get("veredicto", "")).startswith("aprobado"):
                filas[r["usuario"].lower()] = {
                    "usuario": r["usuario"], "etapa": r["veredicto"],
                    "tipo_evidencia": r["veredicto"].replace("aprobado_", ""),
                    "edad_estimada": r.get("edad_estimada", ""), "banda": r.get("banda", ""),
                    "confianza": r.get("confianza_edad", ""), "evidencia": r.get("evidencia", ""),
                    "seguidores": r.get("seguidores", ""), "posts": r.get("posts", "")}
    if os.path.exists(SALIDA):
        for r in csv.DictReader(open(SALIDA, encoding="utf-8-sig")):
            if r.get("aprobado") == "si":
                filas[r["usuario"].lower()] = {
                    "usuario": r["usuario"], "etapa": "aprobado_captions",
                    "tipo_evidencia": "captions", "edad_estimada": r.get("edad_estimada", ""),
                    "banda": r.get("banda", ""), "confianza": r.get("confianza", ""),
                    "evidencia": r.get("evidencia", ""), "seguidores": "", "posts": ""}
    if filas:
        campos = ["usuario", "etapa", "tipo_evidencia", "edad_estimada", "banda", "confianza",
                  "evidencia", "seguidores", "posts"]
        with open(MAESTRO, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(filas.values())
    from collections import Counter
    c = Counter(x["tipo_evidencia"] for x in filas.values())
    log("CONTROLES APROBADOS: %d  (bio %d, institucion %d, captions %d) -> %s"
        % (len(filas), c.get("bio", 0), c.get("institucion", 0), c.get("captions", 0), MAESTRO))
    return len(filas)


def correr(driver, ig, ruta_csv, limite=10 ** 6, reanudar=True, dormir_al_limite=True,
           log=print, tope_cargas=None, contador=None):
    if not os.path.exists(ruta_csv):
        log("CAPTIONS: no hay %s, nada que hacer." % ruta_csv)
        return {}
    filas = [r for r in csv.DictReader(open(ruta_csv, encoding="utf-8-sig")) if r.get("instagram")]
    hechos = {}
    if reanudar and os.path.exists(CKPT):
        hechos = json.load(open(CKPT, encoding="utf-8"))
    pendientes = [r for r in filas if r["instagram"] not in hechos][:limite]
    log("CAPTIONS: %d pendientes, %d ya hechos, %d por hacer (~%.1f h a 1.5 min)"
        % (len(filas), len(hechos), len(pendientes), len(pendientes) * 1.5 / 60.0))
    anomalias, aprobados_nuevos = 0, []
    for n, r in enumerate(pendientes, 1):
        if tope_cargas is not None and contador is not None and contador.get("cargas", 0) >= tope_cargas:
            log("CAPTIONS: tope de cargas del dia alcanzado, paro aqui.")
            break
        u = r["instagram"]
        try:
            caps = leer_captions(driver, ig, u)
            if contador is not None:
                contador["cargas"] = contador.get("cargas", 0) + 1 + len(caps)
            edad, conf, ev = ie.señal_captions(caps)
            ok = edad is not None and conf in ("alta", "media") and ie.EDAD_MIN <= edad <= ie.EDAD_MAX
            hechos[u] = {"usuario": u, "n_captions": len(caps), "aprobado": "si" if ok else "no",
                         "edad_estimada": edad or "", "banda": ie.banda_de(edad) if edad else "",
                         "confianza": conf, "evidencia": ev,
                         "motivo": "aprobado: edad en caption" if ok else (
                             "edad fuera de rango (%s)" % edad if edad else
                             ("sin posts legibles" if not caps else "sin edad en captions"))}
            if ok:
                aprobados_nuevos.append(u)
            anomalias = 0 if caps else anomalias + 1
            log("  [%d/%d] %s %-28s %s" % (n, len(pendientes), "OK-cap " if ok else "       ", u,
                                         hechos[u]["motivo"]))
        except Exception as e:
            log("  [%d/%d]         %-28s ERROR: %s" % (n, len(pendientes), u, e))
            hechos[u] = {"usuario": u, "n_captions": 0, "aprobado": "no", "edad_estimada": "",
                         "banda": "", "confianza": "", "evidencia": "", "motivo": "error: %s" % str(e)[:80]}
            anomalias += 1
        json.dump(hechos, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
        if anomalias >= LIMITE_ANOMALIAS:
            if dormir_al_limite:
                log("  *** %d perfiles seguidos sin posts legibles: posible limite. Duermo %d min."
                    % (anomalias, SIESTA_LIMITE_S // 60))
                time.sleep(SIESTA_LIMITE_S)
                anomalias = 0
                for x in list(hechos.values())[-LIMITE_ANOMALIAS:]:
                    if x["motivo"].startswith("error") or x["motivo"] == "sin posts legibles":
                        hechos.pop(x["usuario"], None)
                json.dump(hechos, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
            else:
                log("  *** %d seguidos sin posts legibles. Corto. Vuelve con --reanudar." % anomalias)
                break
        time.sleep(random.uniform(*PAUSA_PERFIL))

    filas_out = list(hechos.values())
    if filas_out:
        with open(SALIDA, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(filas_out[0].keys()))
            w.writeheader()
            w.writerows(filas_out)
    todos_aprob = [x["usuario"] for x in filas_out if x["aprobado"] == "si"]
    total = _fusionar_aprobados(todos_aprob)
    log("CAPTIONS: %d aprobados en esta etapa (%d nuevos ahora). Lista total de aprobados: %d"
        % (len(todos_aprob), len(aprobados_nuevos), total))
    escribir_maestro(log)
    return hechos


def main():
    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d
    ruta = arg("--csv", os.path.join(DIR, "candidatos_pendientes_formato.csv"))
    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait
    import scrappingData_ig as ig
    driver = webdriver.Chrome()
    try:
        ig.iniciar_sesion(driver, WebDriverWait(driver, ig.ESPERA_LOGIN))
        correr(driver, ig, ruta, limite=int(arg("--limite", 10 ** 6)),
               reanudar="--reanudar" in sys.argv, dormir_al_limite="--dormir-al-limite" in sys.argv)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
