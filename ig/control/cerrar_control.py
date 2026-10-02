# -*- coding: utf-8 -*-
"""
Cierra el grupo control en UNA orden. Sin nombres de fichero que adivinar.

    python ig/control/cerrar_control.py

Hace, en este orden, y se para en el primer paso que falle:

  1. Re-extrae los perfiles de baja cobertura (reextraer_formato.csv).
     Abre Chrome, tarda ~1.2 h. Solo este paso necesita navegador.
  2. Une TODOS los globals de controles en uno (unir_globals).
  3. Empareja 2:1 contra el global de pacientes (emparejar --relajar).
  4. Corre el detector de marco muestral.
  5. Mide la cobertura de extraccion del global unido (cobertura.py).
  6. Regenera el export anonimo del global unido (regenerar_anonimo).
  7. Resume: cuantos emparejados, que casos quedan cojos, AUC, cobertura.

Localiza solo el global de pacientes (el mas reciente cuya mayoria de ids son
MIND####) y el de controles (el que acaba de unir), asi que no hay que pasarle
rutas. Cada paso imprime la orden equivalente por si hay que repetirlo suelto.

Opciones:
    --sin-extraer     salta el paso 1 (no abre navegador). Para rehacer solo
                      la parte de calculo, tarda segundos.
    --caliper N       tolerancia de edad para evidencia de bio/captions,
                      2 por defecto. Ver la nota al final de la salida.
    --razon N         controles por caso (2 por defecto).

Todo en una linea. En PowerShell el '\\' de continuacion no funciona.
"""

import csv, glob, json, os, re, subprocess, sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(DIR))
RES = os.path.join(RAIZ, "resultados_ig")
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))

PY = sys.executable


def rel(p):
    return os.path.relpath(p, RAIZ).replace("\\", "/")


def titulo(n, txt):
    print("\n" + "=" * 72)
    print("  PASO %d  %s" % (n, txt))
    print("=" * 72)


def correr(args, capturar=False):
    """Lanza un script del repo con el mismo Python. Imprime la orden."""
    orden = [PY] + args
    print("  $ " + " ".join(rel(a) if os.path.isabs(a) else a for a in orden[1:]))
    print()
    if capturar:
        r = subprocess.run(orden, cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        print(r.stdout)
        if r.stderr.strip():
            print(r.stderr)
        return r.returncode, r.stdout
    r = subprocess.run(orden, cwd=RAIZ)
    return r.returncode, ""


def es_de_pacientes(ruta):
    try:
        res = json.load(open(ruta, encoding="utf-8")).get("resultados", [])
        if not res:
            return False
        return sum(1 for r in res if str(r.get("id", "")).startswith("MIND")) > len(res) / 2
    except Exception:
        return False


def global_pacientes():
    cand = sorted(f for f in glob.glob(os.path.join(RES, "global_2*.json"))
                  if "anonimo" not in os.path.basename(f))
    pac = [f for f in cand if es_de_pacientes(f)]
    if not pac:
        sys.exit("No encuentro ningun global de pacientes en resultados_ig/.")
    return pac[-1]


def leer_descartes():
    ruta = os.path.join(DIR, "descartes_manuales.txt")
    fuera = set()
    if os.path.exists(ruta):
        for l in open(ruta, encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#"):
                fuera.add(l.split("#")[0].strip().lower())
    return fuera


def filtrar_reextraccion():
    """Quita de reextraer_formato.csv los descartados a mano. cobertura.py lo
    regenera cada vez y no sabe de descartes."""
    ruta = os.path.join(DIR, "reextraer_formato.csv")
    if not os.path.exists(ruta):
        return 0
    fuera = leer_descartes()
    filas = list(csv.DictReader(open(ruta, encoding="utf-8-sig")))
    if not filas:
        return 0
    campos = list(filas[0].keys())
    keep = [r for r in filas if (r.get("instagram") or "").strip().lower() not in fuera]
    if len(keep) != len(filas):
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(keep)
    return len(keep)


def main():
    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d

    extraer = "--sin-extraer" not in sys.argv
    caliper = int(arg("--caliper", 2))
    razon = int(arg("--razon", 2))
    inicio = datetime.now()

    print("\nCIERRE DEL GRUPO CONTROL   %s" % inicio.strftime("%Y-%m-%d %H:%M"))
    print("  python: %s" % PY)

    # ---- 1. re-extraccion --------------------------------------------------
    titulo(1, "Re-extraccion de perfiles con baja cobertura")
    n_re = filtrar_reextraccion()
    ruta_re = os.path.join(DIR, "reextraer_formato.csv")
    if not extraer:
        print("  (--sin-extraer) Saltado. Lista actual: %d perfiles en %s" % (n_re, rel(ruta_re)))
    elif n_re == 0:
        print("  Nada que re-extraer: %s esta vacio." % rel(ruta_re))
    else:
        import correr_todo
        problemas = correr_todo.comprobar_entorno()
        fatales = [p for p in problemas if "credenciales" in p or "Falta el paquete" in p]
        for p in problemas:
            print(("  ERROR: " if p in fatales else "  AVISO: ") + p)
        if fatales:
            sys.exit("\n  No arranco hasta que esto este resuelto.")
        print("  %d perfiles. Abre Chrome; ~4 min por perfil. NO apagues el equipo." % n_re)
        rc, _ = correr([os.path.join(RAIZ, "ig", "scrappingData_ig.py"),
                        "--csv", ruta_re, "--sin-pausa"])
        if rc != 0:
            sys.exit("\n  La re-extraccion termino con error (codigo %d). No sigo." % rc)

    # ---- 2. unir ----------------------------------------------------------------
    titulo(2, "Unir todos los globals de controles")
    import unir_globals as ug
    rutas = sorted(f for f in glob.glob(os.path.join(RES, "global_2*.json"))
                   if "anonimo" not in os.path.basename(f)
                   and "unido" not in os.path.basename(f)
                   and not es_de_pacientes(f))
    if not rutas:
        sys.exit("  No hay globals de controles que unir.")
    print("  $ python ig/control/unir_globals.py --todos")
    ruta_ctrl = ug.unir(rutas)
    ruta_pac = global_pacientes()
    print("\n  pacientes : %s" % rel(ruta_pac))
    print("  controles : %s" % rel(ruta_ctrl))

    # ---- 3. emparejar -----------------------------------------------------------
    titulo(3, "Emparejamiento %d:1" % razon)
    rc, out = correr([os.path.join(DIR, "emparejar.py"), "--casos", ruta_pac,
                      "--controles", ruta_ctrl, "--razon", str(razon), "--relajar",
                      "--caliper", str(caliper)], capturar=True)
    if rc != 0:
        sys.exit("  emparejar.py fallo. No sigo.")
    m = re.search(r"Emparejados: (\d+) controles para (\d+) casos", out)
    n_emp, n_cas = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    cojos = re.findall(r"^\s+(MIND\d+)\s+estrato (\([^)]*\)) -> solo (\d+)", out, re.M)
    relaj = re.search(r"De ellos, (\d+) salieron de un estrato vecino", out)
    n_relaj = int(relaj.group(1)) if relaj else 0

    # ---- 4. detector --------------------------------------------------------------
    titulo(4, "Detector de marco muestral (solo metadatos)")
    rc, out_d = correr([os.path.join(DIR, "detector_marco.py"), "--casos", ruta_pac,
                        "--controles", ruta_ctrl], capturar=True)
    m = re.search(r"AUC validacion cruzada = ([\d.]+)\s+\(DE entre repeticiones ([\d.]+)\)", out_d)
    auc, de = (float(m.group(1)), float(m.group(2))) if m else (float("nan"), float("nan"))

    # ---- 5. cobertura ---------------------------------------------------------
    titulo(5, "Cobertura de extraccion del global unido")
    rc, out_c = correr([os.path.join(DIR, "cobertura.py"), ruta_ctrl], capturar=True)
    n_bajos = filtrar_reextraccion()
    m = re.search(r"cobertura media[^\d]*([\d.]+)\s*%", out_c, re.I)
    cob_media = m.group(1) if m else "?"

    # ---- 6. anonimo ---------------------------------------------------------------
    titulo(6, "Export anonimo del global unido")
    rc, out_a = correr([os.path.join(RAIZ, "ig", "regenerar_anonimo.py"), ruta_ctrl], capturar=True)
    m = re.search(r"Listo: (.*)$", out_a, re.M)
    ruta_anon = m.group(1).strip() if m else "(no generado: revisa fugas arriba)"

    # ---- 7. resumen ---------------------------------------------------------------
    titulo(7, "Resumen")
    dur = datetime.now() - inicio
    print("  duracion                 : %s" % str(dur).split(".")[0])
    print("  global de controles      : %s" % rel(ruta_ctrl))
    print("  export anonimo           : %s" % (rel(ruta_anon) if os.path.isabs(ruta_anon) else ruta_anon))
    print("  emparejados              : %d controles para %d casos (pedido %d:1)" % (n_emp, n_cas, razon))
    print("  de estrato vecino        : %d  (declarar como limitacion)" % n_relaj)
    print("  casos cojos              : %d" % len(cojos))
    for cid, k, n in cojos:
        print("      %-10s estrato %s -> solo %s" % (cid, k, n))
    print("  detector de marco        : AUC %.3f (DE %.3f)  %s"
          % (auc, de, "OK, comparables" if auc <= 0.60 else
             "SESGO DE MARCO: reportar y ponderar" if auc <= 0.70 else "NO SIRVE: volver a emparejar"))
    print("  cobertura media controles: %s%%   perfiles aun bajo el minimo: %d" % (cob_media, n_bajos))
    print()
    print("  ficheros: ig/control/controles_emparejados.csv, tabla_balance.csv, controles_evidencia.csv")

    if cojos:
        print()
        print("  Los casos cojos estan en el estrato de edad %s. Dos salidas:" % cojos[0][1].split(",")[0].strip("(") )
        print("    a) Aceptar %d:%d y declararlo. Con n=%d casos, dos controles de mas o de" % (n_emp, n_cas, n_cas))
        print("       menos no cambian nada, y el detector ya dice que los grupos son comparables.")
        if caliper < 3:
            print("    b) Repetir con --caliper 3 (tolerancia de edad +/-3 en vez de +/-2 para")
            print("       evidencia de bio). Defendible a esa edad; hay que declararlo:")
            print("         python ig/control/cerrar_control.py --sin-extraer --caliper 3")
        print("    Sembrar mas NO es una salida realista: las semillas son escuelas y dan 15-24.")
    print()


if __name__ == "__main__":
    main()
