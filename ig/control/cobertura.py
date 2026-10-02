# -*- coding: utf-8 -*-
"""
Control de calidad: ¿se extrajo de verdad cada perfil, o solo su primera pantalla?

Compara los posts EXTRAIDOS con los que el perfil DECLARA. Es la comprobacion
que faltaba el 07/09/2026: 18 de 73 cuentas control con 15 o mas posts se habian
extraido por debajo del 60%, y una (expocientificactr) al 3%. La cobertura media
de los controles era del 80% frente al 98% de los pacientes.

Eso no es una diferencia entre las personas, es una diferencia entre las
extracciones, y el detector de marco muestral la leia como si fuera real: el AUC
subio de 0.56 a 0.69 en cuanto entraron esos perfiles mal extraidos.

Genera `reextraer_formato.csv` con los que hay que volver a bajar.

Uso:
    python ig/control/cobertura.py resultados_ig/global_X.json [--min 60]
    python ig/control/cobertura.py --casos     (los pacientes, de referencia)
"""

import csv, json, os, sys
import statistics as st
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
from util import numero, id_control

RAIZ = os.path.dirname(os.path.dirname(DIR))


def evaluar(ruta, minimo=60, solo_aprobados=True):
    d = json.load(open(ruta, encoding="utf-8"))
    res = d.get("resultados", d if isinstance(d, list) else [])
    aprob = None
    ruta_ev = os.path.join(DIR, "controles_evidencia.csv")
    if solo_aprobados and os.path.exists(ruta_ev):
        aprob = {r["usuario"].lower() for r in csv.DictReader(open(ruta_ev, encoding="utf-8-sig"))}

    filas, malos = [], []
    for r in res:
        u = (r.get("usuario") or "").strip()
        if aprob is not None and u.lower() not in aprob:
            continue
        if r.get("estado_cuenta") != "publica_con_posts":
            continue
        dec = numero(r.get("posts"))
        # El contador de posts que muestra Instagram cuenta TODO lo que hay en
        # el grid, colaboraciones incluidas. Medir cobertura solo con los posts
        # propios daba un 44% a alguien con 7 propios + 9 colaboraciones = 16
        # de 16 declarados, y lo mandaba a re-extraer sin motivo (9/9/2026).
        todos = r.get("posts_data") or []
        ext = len(todos)
        propios = len([p for p in todos if p.get("es_del_perfil", True)])
        cob = (100.0 * ext / dec) if dec else None
        filas.append((u, dec, ext, cob))
        if dec >= 15 and cob is not None and cob < minimo:
            malos.append((u, dec, ext, cob))

    cobs = [c for _, _, _, c in filas if c is not None]
    print("\nCOBERTURA DE EXTRACCION  (%s)" % os.path.basename(ruta))
    print("  perfiles publicos con posts : %d" % len(filas))
    if cobs:
        print("  cobertura media             : %.0f%%" % st.mean(cobs))
        print("  mediana                     : %.0f%%" % st.median(cobs))
        print("  por debajo del %d%%           : %d" % (minimo, len(malos)))
    if malos:
        print("\n  %-30s %8s %10s %9s" % ("usuario", "declara", "extraidos", "cobertura"))
        print("  " + "-" * 60)
        for u, dec, ext, cob in sorted(malos, key=lambda x: x[3]):
            print("  %-30s %8d %10d %8.0f%%" % (u, dec, ext, cob))
        ruta_out = os.path.join(DIR, "reextraer_formato.csv")
        hoy = datetime.now().strftime("%m/%d/%Y")
        with open(ruta_out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
            for u, _, _, _ in malos:
                w.writerow([id_control(u), "1/1/2010", hoy, u, "", "", ""])
        print("\n  -> %s  (%d perfiles, ~%.1f h)" % (ruta_out, len(malos), len(malos) * 4 / 60.0))
        print("     python ig/scrappingData_ig.py --csv ig/control/reextraer_formato.csv --sin-pausa")
        print("     (sin --reanudar: esos perfiles ya estan en el checkpoint y se saltarian)")
    else:
        print("\n  Todo por encima del %d%%. Nada que volver a extraer." % minimo)
    return malos


def main():
    minimo = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 60
    if "--casos" in sys.argv:
        return evaluar(os.path.join(RAIZ, "resultados_ig", "global_20260828_163758.json"),
                       minimo, solo_aprobados=False)
    rutas = [a for a in sys.argv[1:] if a.endswith(".json")]
    if not rutas:
        sys.exit(__doc__)
    for r in rutas:
        evaluar(r, minimo)


if __name__ == "__main__":
    main()
