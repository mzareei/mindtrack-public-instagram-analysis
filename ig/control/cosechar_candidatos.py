# -*- coding: utf-8 -*-
"""
Cosecha de candidatos a control, con EVIDENCIA DE EDAD desde el origen.

Lo que cambio el 3 sep 2026 y por que. El triaje de 667 perfiles aprobo 2 (0.3%)
exigiendo edad escrita en la biografia. No era un bug: la mayoria de la gente
joven no escribe su edad en ningun lado, el 39% de las cuentas es privada, y
entre quienes comentan en la cuenta de una prepa hay padres, maestros y personal.
Escalar eso no llega a 60 controles.

Lo que si cambia la tasa base es DE DONDE sale la evidencia de edad. Ahora la
cosecha distingue dos cosas que antes mezclaba:

  ETIQUETADOS POR LA INSTITUCION. Cuando @prepa7udeg publica "felicidades a
  @fulana y @mengano de 6to semestre", o una foto de "Generacion 2023-2026", la
  escuela misma esta nombrando a esa persona como alumno actual. Es evidencia de
  edad individual, explicita, de un tercero, con rastro (que escuela, que post,
  que fecha). Se guarda con tipo_evidencia="institucion" y el shortcode del post.

  COMENTARISTAS. Cualquiera que comento o aparece enlazado en la pagina. Sin
  evidencia de edad por si mismos (tipo_evidencia="ninguna"). Van al triaje y,
  si pasan todo menos la edad, a la etapa de captions.

Cada semilla lleva una CLASE que dice si puede aportar evidencia y de que banda:
  prepa            15-18   la institucion etiqueta alumnos
  universidad      18-24   idem
  org_estudiantil  15-24   sociedad de alumnos, equipo, colectivo de una escuela
  local            --      agregadores y eventos: solo comentaristas, sin evidencia
  hashtag          --      idem

Uso:
    python ig/control/cosechar_candidatos.py --dry-run
    python ig/control/cosechar_candidatos.py [--limite N] [--reanudar]
                                              [--semillas-extra ig/control/semillas_descubiertas.txt]
"""

import csv, json, os, random, re, sys, time
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(DIR))
sys.path.insert(0, DIR)
from exclusiones import cargar_exclusiones, _norm

# CONFIG
# Cavar hondo en cada semilla: las etiquetas de alumnos aparecen en posts de
# eventos, premios y graduaciones, que no siempre son los mas recientes.
MAX_POSTS_POR_SEMILLA = 40
MAX_COMENTARISTAS_POR_SEMILLA = 250   # los etiquetados NO tienen tope
PAUSA = (2.5, 6.0)
PAUSA_SEMILLA = (20, 45)
LIMITE_ANOMALIAS = 4

SALIDA = os.path.join(DIR, "candidatos.csv")
CKPT = os.path.join(DIR, "cosecha_en_curso.json")

CLASES = {
    "prepa":           {"banda": "15-18", "evidencia": True},
    "secundaria":      {"banda": "12-15", "evidencia": True},
    "universidad":     {"banda": "18-24", "evidencia": True},
    "org_estudiantil": {"banda": "15-24", "evidencia": True},
    "local":           {"banda": "",      "evidencia": False},
    "hashtag":         {"banda": "",      "evidencia": False},
}

# SEMILLAS
# Las de abajo se localizaron por busqueda web o aparecieron en cosechas
# anteriores como cuentas institucionales. Las marcadas SIN VERIFICAR no se han
# abierto todavia: una semilla que devuelve 0 dos veces seguidas se apaga sola.
SEMILLAS = [
    # --- preparatorias UdeG, zona metropolitana ---
    {"tipo": "cuenta", "valor": "sems_udeg",          "clase": "prepa", "nota": "SEMS, paraguas"},
    {"tipo": "cuenta", "valor": "prepa7udeg",         "clase": "prepa", "nota": "Prepa 7, Zapopan"},
    {"tipo": "cuenta", "valor": "p5udg",              "clase": "prepa", "nota": "Prepa 5"},
    {"tipo": "cuenta", "valor": "prepa_3udg",         "clase": "prepa", "nota": "Prepa 3"},
    {"tipo": "cuenta", "valor": "prepaveintiuno_udg", "clase": "prepa", "nota": "Prepa 21"},
    {"tipo": "cuenta", "valor": "prepa9udg",          "clase": "prepa", "nota": "Prepa 9, Zapopan"},
    {"tipo": "cuenta", "valor": "prepa20udg",         "clase": "prepa", "nota": "Prepa 20, Zapopan"},
    {"tipo": "cuenta", "valor": "prepaquince",        "clase": "prepa", "nota": "Prepa 15, hallada en cosecha"},
    {"tipo": "cuenta", "valor": "preparatoria_10",    "clase": "prepa", "nota": "Prepa 10, hallada en cosecha"},
    {"tipo": "cuenta", "valor": "politecnicomatuteremus", "clase": "prepa", "nota": "Politecnico UdeG, hallada"},
    {"tipo": "cuenta", "valor": "escuela.vocacional.udg", "clase": "prepa", "nota": "Vocacional UdeG, hallada"},
    {"tipo": "cuenta", "valor": "prepajal",           "clase": "prepa", "nota": "Prepa de Jalisco, hallada"},
    {"tipo": "cuenta", "valor": "prepasjv",           "clase": "prepa", "nota": "hallada, SIN VERIFICAR municipio"},
    # --- preparatorias UdeG regionales (Jalisco, fuera de la ZMG) ---
    {"tipo": "cuenta", "valor": "prepa_tlajomulco",   "clase": "prepa", "nota": "Tlajomulco, hallada"},
    {"tipo": "cuenta", "valor": "prepa_cd.guzman",    "clase": "prepa", "nota": "Cd. Guzman, hallada"},
    {"tipo": "cuenta", "valor": "prepazacoalco",      "clase": "prepa", "nota": "Zacoalco, hallada"},
    {"tipo": "cuenta", "valor": "preparatoria_sanmiguelelalto", "clase": "prepa", "nota": "hallada"},
    {"tipo": "cuenta", "valor": "mazamitlaprepa",     "clase": "prepa", "nota": "Mazamitla, hallada"},
    {"tipo": "cuenta", "valor": "prep.haciendasdesanta", "clase": "prepa", "nota": "hallada"},
    # --- centros universitarios ---
    {"tipo": "cuenta", "valor": "udegcucei",          "clase": "universidad", "nota": "CUCEI"},
    {"tipo": "cuenta", "valor": "cucs_udeg",          "clase": "universidad", "nota": "CUCS"},
    {"tipo": "cuenta", "valor": "cutlajo",            "clase": "universidad", "nota": "CUTlajomulco, hallada"},
    {"tipo": "cuenta", "valor": "cu_chapala",         "clase": "universidad", "nota": "CU Chapala, hallada"},
    {"tipo": "cuenta", "valor": "coordilcfd",         "clase": "universidad", "nota": "Lic. Cultura Fisica, hallada"},
    {"tipo": "cuenta", "valor": "cirujanodentista_cucs", "clase": "universidad", "nota": "hallada"},
    # --- organizaciones estudiantiles (etiquetan a sus miembros) ---
    {"tipo": "cuenta", "valor": "xpresion_feu",       "clase": "org_estudiantil", "nota": "FEU, hallada en piloto"},
    {"tipo": "cuenta", "valor": "xpresionp7",         "clase": "org_estudiantil", "nota": "Prepa 7, hallada"},
    {"tipo": "cuenta", "valor": "xpresioncut",        "clase": "org_estudiantil", "nota": "hallada"},
    {"tipo": "cuenta", "valor": "revolucion_p3",      "clase": "org_estudiantil", "nota": "Prepa 3, hallada"},
    {"tipo": "cuenta", "valor": "revolucion_p2",      "clase": "org_estudiantil", "nota": "Prepa 2, hallada"},
    {"tipo": "cuenta", "valor": "robotica.cucei",     "clase": "org_estudiantil", "nota": "hallada"},
    {"tipo": "cuenta", "valor": "ballet_folcorico_cucei", "clase": "org_estudiantil", "nota": "hallada"},
    {"tipo": "cuenta", "valor": "brigadasdepazcucei", "clase": "org_estudiantil", "nota": "hallada"},
    {"tipo": "cuenta", "valor": "primercontactocucei", "clase": "org_estudiantil", "nota": "hallada"},
    {"tipo": "cuenta", "valor": "cea.cucs",           "clase": "org_estudiantil", "nota": "hallada"},
    # --- locales: solo comentaristas, sin evidencia ---
    {"tipo": "cuenta", "valor": "quepasaguadalajara", "clase": "local"},
    {"tipo": "cuenta", "valor": "kutu.fest",          "clase": "local"},
    {"tipo": "hashtag", "valor": "prepaudg",          "clase": "hashtag"},
    # zapopan como hashtag se PROBO: 152 candidatos, casi todo turismo, gobierno
    # y negocios, 0 aprobados. Fuera.
]

_RE_HANDLE = re.compile(r"^/([A-Za-z0-9._]{2,30})/?$")
_RE_MENCION = re.compile(r"@([A-Za-z0-9._]{2,30})")
_RESERVADOS = {
    "explore", "reels", "reel", "p", "stories", "accounts", "direct", "about",
    "legal", "privacy", "terms", "developer", "api", "challenge", "emails",
    "session", "topics", "s", "web", "your_activity", "tv", "igtv",
}
COLUMNAS = ["usuario", "tipo_semilla", "semilla", "clase_semilla", "banda_esperada",
            "tipo_evidencia", "shortcode_evidencia", "fecha_cosecha"]


def _pausa(rango=PAUSA):
    time.sleep(random.uniform(*rango))


def _handles_en_pagina(driver):
    js = ("return Array.from(document.querySelectorAll(\"a[href^='/']\"))"
          "            .map(function(a){return a.getAttribute('href');});")
    fuera = set()
    for href in driver.execute_script(js) or []:
        m = _RE_HANDLE.match((href or "").split("?")[0])
        if m and m.group(1).lower() not in _RESERVADOS:
            fuera.add(m.group(1).lower())
    return fuera


def _links_posts(driver):
    js = ("return Array.from(document.querySelectorAll(\"a[href*='/p/'], a[href*='/reel/']\"))"
          "            .map(function(a){return a.href.split('?')[0];});")
    vistos, salida = set(), []
    for u in driver.execute_script(js) or []:
        if u not in vistos:
            vistos.add(u)
            salida.append(u)
    return salida


def _usertags_en_pagina(driver, ig):
    """Etiquetas EN LA FOTO (no en el caption). Las escuelas etiquetan a los
    alumnos muchas veces asi, y eso no aparece en el texto del caption. El JSON
    embebido de la pagina del post trae `usertags` con el username de cada
    persona etiquetada; se recorre igual que hace obtener_fecha_post() para la
    fecha."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(driver.page_source, "html.parser")
    except Exception:
        return set()
    fuera = set()
    for script in soup.find_all("script", attrs={"type": "application/json"}):
        try:
            data = json.loads(script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for nodo in ig._walk_json(data):
            ut = nodo.get("usertags")
            if not isinstance(ut, dict):
                continue
            for item in ut.get("in") or []:
                u = ((item or {}).get("user") or {}).get("username")
                if isinstance(u, str) and u:
                    fuera.add(u.lower())
    return fuera


def _shortcode(url):
    m = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else ""


def cargar_semillas_extra(ruta):
    """Archivo de texto: handle,clase[,nota] por linea. Lo escribe
    filtrar_candidatos.py con las cuentas institucionales que va encontrando."""
    extra = []
    if not ruta or not os.path.exists(ruta):
        return extra
    for linea in open(ruta, encoding="utf-8"):
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        partes = [p.strip() for p in linea.split(",")]
        if len(partes) < 2 or partes[1] not in CLASES:
            continue
        extra.append({"tipo": "cuenta", "valor": partes[0], "clase": partes[1],
                      "nota": partes[2] if len(partes) > 2 else "descubierta"})
    return extra


def cosechar_semilla(driver, semilla, excluidos, ya_vistos, ig):
    """Devuelve la lista de candidatos nuevos de esta semilla."""
    tipo, valor = semilla["tipo"], semilla["valor"]
    clase = semilla.get("clase", "local")
    cfg = CLASES.get(clase, CLASES["local"])
    if tipo == "cuenta":
        url = "https://www.instagram.com/%s/" % valor
    elif tipo == "hashtag":
        url = "https://www.instagram.com/explore/tags/%s/" % valor
    else:
        return []

    driver.get(url)
    _pausa()
    for _ in range(3):
        driver.execute_script("window.scrollBy(0, 1600);")
        _pausa((1.0, 2.5))
    posts = _links_posts(driver)[:MAX_POSTS_POR_SEMILLA]

    etiquetados = {}      # handle -> shortcode donde la institucion lo nombro
    comentaristas = set()
    for post in posts:
        try:
            driver.get(post)
            _pausa()
            if cfg["evidencia"]:
                cap = ig.extraer_caption_post(driver) or {}
                texto = " ".join(str(cap.get(k) or "") for k in ("caption", "caption_raw"))
                nombrados = {h.lower() for h in _RE_MENCION.findall(texto)}
                nombrados |= _usertags_en_pagina(driver, ig)      # etiquetas en la foto
                for h in nombrados:
                    if h != valor.lower() and h not in etiquetados:
                        etiquetados[h] = _shortcode(post)
            comentaristas |= _handles_en_pagina(driver)
        except Exception as e:
            print("     aviso: %s -> %s" % (post[-14:], e))

    comentaristas -= set(etiquetados)
    hoy = datetime.now().date().isoformat()
    nuevos = []
    for h, sc in etiquetados.items():
        if h in excluidos or h in ya_vistos or h == valor.lower() or h in _RESERVADOS:
            continue
        ya_vistos.add(h)
        nuevos.append({"usuario": h, "tipo_semilla": tipo, "semilla": valor,
                       "clase_semilla": clase, "banda_esperada": cfg["banda"],
                       "tipo_evidencia": "institucion", "shortcode_evidencia": sc,
                       "fecha_cosecha": hoy})
    n_com = 0
    for h in sorted(comentaristas):
        if h in excluidos or h in ya_vistos or h == valor.lower():
            continue
        if n_com >= MAX_COMENTARISTAS_POR_SEMILLA:
            break
        ya_vistos.add(h)
        n_com += 1
        nuevos.append({"usuario": h, "tipo_semilla": tipo, "semilla": valor,
                       "clase_semilla": clase, "banda_esperada": cfg["banda"],
                       "tipo_evidencia": "ninguna", "shortcode_evidencia": "",
                       "fecha_cosecha": hoy})
    return nuevos, len(etiquetados), n_com


def escribir(candidatos):
    with open(SALIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        for c in candidatos:
            w.writerow({k: c.get(k, "") for k in COLUMNAS})
    ruta = SALIDA.replace("candidatos.csv", "candidatos_formato.csv")
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
        hoy = datetime.now().strftime("%m/%d/%Y")
        for n, c in enumerate(candidatos, 1):
            w.writerow(["CTRL%04d" % n, "1/1/2010", hoy, c["usuario"], "", "", ""])
    return ruta


def correr(driver, ig, semillas, limite=10 ** 6, reanudar=True, log=print, contador=None, tope_cargas=None):
    """Cosecha todas las semillas pendientes. Reutilizable desde el orquestador."""
    excluidos = cargar_exclusiones()
    candidatos, ya_vistos, hechas, muertas = [], set(), set(), {}
    if reanudar and os.path.exists(CKPT):
        prev = json.load(open(CKPT, encoding="utf-8"))
        # Un checkpoint de la version anterior no distingue etiquetados de
        # comentaristas: hay que volver a visitar las semillas. Se archiva.
        if prev.get("candidatos") and "tipo_evidencia" not in prev["candidatos"][0]:
            viejo = CKPT + ".v1_sin_evidencia"
            os.replace(CKPT, viejo)
            log("COSECHA: checkpoint anterior sin evidencia archivado en %s; se recosecha." % viejo)
            prev = {}
        candidatos = prev.get("candidatos", [])
        ya_vistos = {c["usuario"] for c in candidatos}
        hechas = set(prev.get("semillas_hechas", []))
        muertas = prev.get("semillas_muertas", {})
    pendientes = [s for s in semillas
                  if "%s:%s" % (s["tipo"], s["valor"]) not in hechas
                  and muertas.get(s["valor"], 0) < 2]
    log("COSECHA: %d semillas pendientes, %d candidatos previos, %d excluidos"
        % (len(pendientes), len(candidatos), len(excluidos)))
    anomalias = 0
    nuevos_total = 0
    for n, s in enumerate(pendientes, 1):
        if nuevos_total >= limite:
            break
        if tope_cargas is not None and contador is not None and contador.get("cargas", 0) >= tope_cargas:
            log("COSECHA: tope de cargas del dia alcanzado; el resto de semillas espera al siguiente ciclo.")
            break
        clave = "%s:%s" % (s["tipo"], s["valor"])
        try:
            nuevos, n_etq, n_com = cosechar_semilla(driver, s, excluidos, ya_vistos, ig)
            if contador is not None:
                contador["cargas"] = contador.get("cargas", 0) + 1 + MAX_POSTS_POR_SEMILLA
        except Exception as e:
            log("  [%d/%d] %s ERROR %s" % (n, len(pendientes), clave, e))
            nuevos, n_etq, n_com = [], 0, 0
        candidatos += nuevos
        nuevos_total += len(nuevos)
        hechas.add(clave)
        if not nuevos:
            muertas[s["valor"]] = muertas.get(s["valor"], 0) + 1
            anomalias += 1
        else:
            anomalias = 0
        log("  [%d/%d] %-28s +%d  (etiquetados %d, comentaristas %d)  total %d"
            % (n, len(pendientes), clave, len(nuevos), n_etq, n_com, len(candidatos)))
        json.dump({"candidatos": candidatos, "semillas_hechas": sorted(hechas),
                   "semillas_muertas": muertas},
                  open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
        if anomalias >= LIMITE_ANOMALIAS:
            log("  *** %d semillas seguidas sin nada: posible limite. Pauso la cosecha." % anomalias)
            break
        _pausa(PAUSA_SEMILLA)
    if candidatos:
        escribir(candidatos)
    inst = sum(1 for c in candidatos if c.get("tipo_evidencia") == "institucion")
    log("COSECHA: %d candidatos en total, %d con evidencia institucional -> %s"
        % (len(candidatos), inst, SALIDA))
    return candidatos


def main():
    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d
    semillas = SEMILLAS + cargar_semillas_extra(arg("--semillas-extra",
                                                    os.path.join(DIR, "semillas_descubiertas.txt")))
    limite = int(arg("--limite", 10 ** 6))
    if "--dry-run" in sys.argv:
        print("\nSEMILLAS (%d):" % len(semillas))
        for s in semillas:
            print("  [%-7s] %-30s clase=%-16s banda=%-6s %s" % (
                s["tipo"], s["valor"], s.get("clase", ""), CLASES[s.get("clase", "local")]["banda"],
                s.get("nota", "")))
        print("\nDry run: no se abrio navegador.")
        return
    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait
    import scrappingData_ig as ig
    driver = webdriver.Chrome()
    try:
        ig.iniciar_sesion(driver, WebDriverWait(driver, ig.ESPERA_LOGIN))
        correr(driver, ig, semillas, limite=limite, reanudar="--reanudar" in sys.argv)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
