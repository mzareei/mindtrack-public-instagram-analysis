# -*- coding: utf-8 -*-
"""
Orquestador: deja esto corriendo y vuelve cuando haya 60 controles.

Ciclo (se repite hasta llegar al objetivo o agotar semillas):

  1. cosechar   semillas pendientes + las que se descubrieron en el ciclo anterior
  2. filtrar    marcas, años imposibles; y promueve escuelas nuevas a semillas
  3. triaje     pagina de perfil, 3 veredictos (bio / institucion / pendiente)
  4. captions   posts de los pendientes, edad en primera persona
  5. contar     si aprobados >= objetivo: extraccion completa de los aprobados y fin

Seguridad para correr dias seguidos:
  - tope de cargas de pagina por dia (por defecto 3,000); al llegar duerme
    hasta el dia siguiente
  - cada etapa duerme 45 min y reintenta si Instagram empieza a cortar
  - navegador nuevo y login en cada ciclo, pausa entre ciclos
  - todo con checkpoint: se puede matar y relanzar con la misma orden
  - estado_control.json y correr_todo.log dicen en que va sin abrir nada

Uso:
    python ig/control/correr_todo.py --objetivo 60
    python ig/control/correr_todo.py --objetivo 60 --tope-dia 3000 --sin-extraer
    python ig/control/correr_todo.py --estado          (solo imprime el estado)
"""

import csv, json, os, subprocess, sys, time
from datetime import datetime, date, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(DIR))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))

ESTADO = os.path.join(DIR, "estado_control.json")


def cargar_env():
    """Lee RAIZ/.env y mete IG_USUARIO / IG_PASSWORD en el entorno si no
    estan. No depende de python-dotenv: si se lanza con el Python del sistema
    en vez del del venv, dotenv no existe y el scraper se queda sin
    credenciales. Eso fue lo que paso el 3 sep."""
    if os.environ.get("IG_USUARIO") and os.environ.get("IG_PASSWORD"):
        return True
    ruta = os.path.join(RAIZ, ".env")
    if os.path.exists(ruta):
        for linea in open(ruta, encoding="utf-8"):
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    return bool(os.environ.get("IG_USUARIO") and os.environ.get("IG_PASSWORD"))


def comprobar_entorno():
    """Falla RAPIDO y con un mensaje claro antes de abrir Chrome."""
    problemas = []
    if not cargar_env():
        problemas.append("No hay credenciales. Debe existir C:\\Github\\Mindtrack\\.env con\n"
                         "     IG_USUARIO=...\n     IG_PASSWORD=...\n"
                         "   (copia .env.example). O exportalas como variables de entorno.")
    for mod in ("selenium", "bs4", "requests"):
        try:
            __import__(mod)
        except ImportError:
            problemas.append("Falta el paquete '%s' en este Python: %s" % (mod, sys.executable))
    en_venv = ".venv" in sys.executable.lower() or "venv" in sys.executable.lower()
    if not en_venv:
        problemas.append("Este Python NO es el del venv: %s\n"
                         "   Activa el venv primero:   .\\.venv\\Scripts\\Activate.ps1\n"
                         "   o lanza con el python del venv:   .\\.venv\\Scripts\\python.exe ig/control/correr_todo.py --objetivo 60"
                         % sys.executable)
    return problemas
LOG = os.path.join(DIR, "correr_todo.log")
PAUSA_ENTRE_CICLOS_S = 10 * 60
CICLOS_MAX = 40


def log(msg):
    linea = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(linea, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def cargar_estado():
    if os.path.exists(ESTADO):
        return json.load(open(ESTADO, encoding="utf-8"))
    return {"ciclo": 0, "aprobados": 0, "dia": "", "cargas_hoy": 0, "historial": []}


def guardar_estado(e):
    e["actualizado"] = datetime.now().isoformat(timespec="seconds")
    json.dump(e, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def contar_aprobados():
    import verificar_captions as vc
    return vc.escribir_maestro(log=lambda *_: None)


def n_lineas(ruta):
    if not os.path.exists(ruta):
        return 0
    return sum(1 for r in csv.DictReader(open(ruta, encoding="utf-8-sig")) if any(r.values()))


def usuarios_de(ruta):
    if not os.path.exists(ruta):
        return set()
    return {r["usuario"].lower() for r in csv.DictReader(open(ruta, encoding="utf-8-sig")) if r.get("usuario")}


def semillas_de(ruta):
    if not os.path.exists(ruta):
        return set()
    return {l.split(",")[0].strip().lower() for l in open(ruta, encoding="utf-8")
            if l.strip() and not l.startswith("#")}


def esperar_dia_nuevo(estado):
    manana = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()) + timedelta(minutes=5)
    seg = (manana - datetime.now()).total_seconds()
    log("Tope diario de cargas alcanzado (%d). Duermo hasta %s." % (estado["cargas_hoy"], manana.strftime("%H:%M")))
    time.sleep(max(60, seg))


def nuevo_dia(estado):
    hoy = date.today().isoformat()
    if estado.get("dia") != hoy:
        estado["dia"], estado["cargas_hoy"] = hoy, 0


def ciclo(estado, objetivo, tope_dia):
    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait
    import scrappingData_ig as ig
    import cosechar_candidatos as cc
    import triaje
    import verificar_captions as vc

    contador = {"cargas": estado["cargas_hoy"]}
    antes_cand = usuarios_de(os.path.join(DIR, "candidatos.csv"))
    antes_sem = semillas_de(os.path.join(DIR, "semillas_descubiertas.txt"))

    driver = webdriver.Chrome()
    try:
        ig.iniciar_sesion(driver, WebDriverWait(driver, ig.ESPERA_LOGIN))

        # 1. cosecha
        semillas = cc.SEMILLAS + cc.cargar_semillas_extra(os.path.join(DIR, "semillas_descubiertas.txt"))
        # Universidades primero: el hueco del emparejamiento esta en 22-29 y las
        # prepas no lo llenan.
        semillas = sorted(semillas, key=lambda s_: 0 if s_.get("clase") == "universidad" else 1)
        cc.correr(driver, ig, semillas, reanudar=True, log=log, contador=contador,
                  tope_cargas=int(tope_dia * 0.4))

        # 2. filtro (sin navegador)
        r = subprocess.run([sys.executable, os.path.join(DIR, "filtrar_candidatos.py")],
                           capture_output=True, text=True, cwd=RAIZ)
        for l in (r.stdout or "").splitlines():
            if l.strip():
                log("  filtro | " + l.strip())

        # 3. triaje
        triaje.correr(driver, ig, os.path.join(DIR, "candidatos_formato.csv"), reanudar=True,
                      dormir_al_limite=True, log=log, tope_cargas=tope_dia, contador=contador)
        estado["cargas_hoy"] = contador["cargas"]
        guardar_estado(estado)

        # 4. captions
        if contador["cargas"] < tope_dia:
            vc.correr(driver, ig, os.path.join(DIR, "candidatos_pendientes_formato.csv"), reanudar=True,
                      dormir_al_limite=True, log=log, tope_cargas=tope_dia, contador=contador)
            estado["cargas_hoy"] = contador["cargas"]
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    despues_cand = usuarios_de(os.path.join(DIR, "candidatos.csv"))
    despues_sem = semillas_de(os.path.join(DIR, "semillas_descubiertas.txt"))
    return len(despues_cand - antes_cand), len(despues_sem - antes_sem)


def extraer_aprobados():
    ruta = os.path.join(DIR, "candidatos_aprobados_formato.csv")
    log("EXTRACCION COMPLETA de los aprobados: %s" % ruta)
    subprocess.run([sys.executable, os.path.join(RAIZ, "ig", "scrappingData_ig.py"),
                    "--csv", ruta, "--reanudar", "--sin-pausa"], cwd=RAIZ)
    log("Extraccion terminada. Siguiente: python ig/control/emparejar.py --controles resultados_ig/global_XXXX.json")


def imprimir_estado():
    e = cargar_estado()
    n = contar_aprobados()
    print("\nESTADO DEL GRUPO CONTROL")
    print("  aprobados        : %d" % n)
    print("  ciclos corridos  : %d" % e.get("ciclo", 0))
    print("  cargas hoy       : %d (%s)" % (e.get("cargas_hoy", 0), e.get("dia", "")))
    print("  actualizado      : %s" % e.get("actualizado", ""))
    for h in e.get("historial", [])[-6:]:
        print("   ciclo %2d  %s  aprobados=%d  candidatos+%d  semillas+%d"
              % (h["ciclo"], h["hora"], h["aprobados"], h["cand_nuevos"], h["sem_nuevas"]))
    print("  detalle: %s\n" % os.path.join(DIR, "controles_evidencia.csv"))


def main():
    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d
    if "--estado" in sys.argv:
        return imprimir_estado()
    objetivo = int(arg("--objetivo", 60))
    tope_dia = int(arg("--tope-dia", 3000))
    extraer = "--sin-extraer" not in sys.argv

    estado = cargar_estado()
    log("=" * 70)
    log("ARRANQUE  objetivo=%d  tope_dia=%d  ciclo previo=%d  python=%s"
        % (objetivo, tope_dia, estado["ciclo"], sys.executable))
    problemas = comprobar_entorno()
    fatales = [p for p in problemas if "credenciales" in p or "Falta el paquete" in p]
    for p in problemas:
        log(("ERROR: " if p in fatales else "AVISO: ") + p)
    if fatales:
        log("No arranco hasta que esto este resuelto.")
        sys.exit(1)
    sin_avance = 0
    while estado["ciclo"] < CICLOS_MAX:
        nuevo_dia(estado)
        if estado["cargas_hoy"] >= tope_dia:
            esperar_dia_nuevo(estado)
            nuevo_dia(estado)
        estado["ciclo"] += 1
        log("--- ciclo %d ---" % estado["ciclo"])
        try:
            cand_nuevos, sem_nuevas = ciclo(estado, objetivo, tope_dia)
        except Exception as e:
            msg = str(e)
            # Errores de configuracion: no tiene sentido reintentar en 15 min.
            if any(t in msg.lower() for t in ("credenciales", "no module named", "chromedriver",
                                               "cannot find chrome", "session not created")):
                log("ERROR de configuracion, no reintento: %s" % msg)
                sys.exit(1)
            log("ERROR en el ciclo: %s. Espero 15 min y sigo." % msg)
            time.sleep(15 * 60)
            continue
        aprobados = contar_aprobados()
        estado["aprobados"] = aprobados
        estado["historial"].append({"ciclo": estado["ciclo"], "hora": datetime.now().strftime("%m-%d %H:%M"),
                                    "aprobados": aprobados, "cand_nuevos": cand_nuevos, "sem_nuevas": sem_nuevas})
        guardar_estado(estado)
        log("CICLO %d: aprobados=%d/%d  candidatos nuevos=%d  semillas nuevas=%d  cargas hoy=%d"
            % (estado["ciclo"], aprobados, objetivo, cand_nuevos, sem_nuevas, estado["cargas_hoy"]))

        if aprobados >= objetivo:
            log("OBJETIVO ALCANZADO: %d controles con evidencia. Ver controles_evidencia.csv" % aprobados)
            if extraer:
                extraer_aprobados()
            return
        if cand_nuevos == 0 and sem_nuevas == 0:
            sin_avance += 1
            if sin_avance >= 2:
                log("Dos ciclos sin candidatos ni semillas nuevas: se agotaron las semillas.")
                log("Añade semillas en cosechar_candidatos.py o semillas_descubiertas.txt y relanza.")
                return
        else:
            sin_avance = 0
        log("Pausa de %d min antes del siguiente ciclo." % (PAUSA_ENTRE_CICLOS_S // 60))
        time.sleep(PAUSA_ENTRE_CICLOS_S)
    log("Tope de %d ciclos. Aprobados: %d." % (CICLOS_MAX, estado["aprobados"]))


if __name__ == "__main__":
    main()
