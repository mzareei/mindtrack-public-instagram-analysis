# -*- coding: utf-8 -*-
"""
Une varios global_*.json de controles en uno solo.

Por que hace falta. Cada corrida del scraper escribe su propio global con SOLO
los perfiles de esa corrida. Los controles se han ido extrayendo en tandas (la
grande del 05/09 y la de los 33 que faltaban del 07/09), asi que ningun fichero
tiene el grupo control completo, y `emparejar.py` solo lee uno. Sin unirlos,
emparejas contra un subconjunto y no te enteras.

Si un usuario aparece en dos corridas se queda la version con MAS posts (la mas
completa), no la mas reciente: una recorrida puede haber salido corta por
throttling.

Uso:
    python ig/control/unir_globals.py resultados_ig/global_A.json resultados_ig/global_B.json
    python ig/control/unir_globals.py --todos        (todos los global_2*.json de controles)
"""

import glob, json, os, sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(DIR))
RES = os.path.join(RAIZ, "resultados_ig")


def _posts(r):
    return len(r.get("posts_data") or [])


def unir(rutas, salida=None):
    porusuario = {}
    for ruta in rutas:
        d = json.load(open(ruta, encoding="utf-8"))
        res = d.get("resultados", d if isinstance(d, list) else [])
        nuevos = repetidos = 0
        for r in res:
            u = (r.get("usuario") or r.get("username") or "").strip().lower()
            if not u:
                continue
            if u in porusuario:
                repetidos += 1
                if _posts(r) > _posts(porusuario[u]):
                    porusuario[u] = r
            else:
                porusuario[u] = r
                nuevos += 1
        print("  %-34s %3d perfiles (%d nuevos, %d repetidos)"
              % (os.path.basename(ruta), len(res), nuevos, repetidos))

    salida = salida or os.path.join(RES, "global_controles_unido_%s.json"
                                    % datetime.now().strftime("%Y%m%d_%H%M%S"))
    json.dump({"ejecucion": "unido", "completados": len(porusuario),
               "resultados": list(porusuario.values())},
              open(salida, "w", encoding="utf-8"), ensure_ascii=False)
    print("\n  UNIDO: %d perfiles unicos -> %s" % (len(porusuario), salida))
    return salida


def main():
    if "--todos" in sys.argv:
        rutas = sorted(f for f in glob.glob(os.path.join(RES, "global_2*.json"))
                       if "anonimo" not in os.path.basename(f)
                       and "unido" not in os.path.basename(f))
        # Fuera el global de pacientes: aqui solo se unen controles.
        def es_control(f):
            try:
                res = json.load(open(f, encoding="utf-8")).get("resultados", [])
                return sum(1 for r in res if str(r.get("id", "")).startswith("MIND")) <= len(res) / 2
            except Exception:
                return False
        rutas = [f for f in rutas if es_control(f)]
    else:
        rutas = [a for a in sys.argv[1:] if a.endswith(".json")]
    if not rutas:
        sys.exit(__doc__)
    print("\nUNIENDO GLOBALS DE CONTROLES")
    unir(rutas)


if __name__ == "__main__":
    main()
