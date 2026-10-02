# -*- coding: utf-8 -*-
"""
Piloto: mide el rendimiento real del embudo antes de gastar la noche entera.

La corrida completa de controles cuesta horas. Las tasas del embudo (cuantos
perfiles son publicos con posts, en cuantos se puede leer la edad, cuantos caben
en la envolvente) son estimaciones hasta que se miden con estas semillas
concretas. Un piloto de 50 perfiles cuesta ~3 horas y dice exactamente cuantos
candidatos hacen falta en total. Sin el, o te quedas corto y hay que volver a
sembrar, o extraes 400 perfiles de mas.

Uso:
    # 1. preparar el piloto
    python ig/control/piloto.py --n 50
    # 2. extraerlo con el scraper de siempre (~3 h)
    python ig/scrappingData_ig.py --csv ig/control/candidatos_piloto.csv
    # 3. medir y extrapolar
    python ig/control/piloto.py --medir resultados_ig/global_XXXX.json [--objetivo 60]
"""

import csv, json, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inferir_edad as ie
from util import numero, categoria_profesional

DIR = os.path.dirname(os.path.abspath(__file__))


def _ruta(*p):
    raiz = os.path.dirname(os.path.dirname(DIR))
    return os.path.join(raiz, *p)


def preparar(n):
    filas = list(csv.DictReader(open(os.path.join(DIR, "candidatos.csv"), encoding="utf-8-sig")))
    if not filas:
        sys.exit("candidatos.csv esta vacio.")
    # Reparto proporcional por semilla, para que el piloto mida TODAS las
    # semillas y no solo la primera. Si solo se toman los primeros 50 se estaria
    # midiendo el rendimiento de una o dos semillas.
    por_semilla = {}
    for f in filas:
        por_semilla.setdefault(f["semilla"], []).append(f)
    elegidos, i = [], 0
    while len(elegidos) < min(n, len(filas)):
        avanzo = False
        for s in sorted(por_semilla):
            if i < len(por_semilla[s]) and len(elegidos) < n:
                elegidos.append(por_semilla[s][i])
                avanzo = True
        if not avanzo:
            break
        i += 1

    ruta = os.path.join(DIR, "candidatos_piloto.csv")
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
        hoy = datetime.now().strftime("%m/%d/%Y")
        for k, c in enumerate(elegidos, 1):
            w.writerow(["PILO%04d" % k, "1/1/2010", hoy, c["usuario"], "", "", ""])

    from collections import Counter
    print("\nPILOTO PREPARADO: %d perfiles, repartidos entre todas las semillas" % len(elegidos))
    for s, c in Counter(e["semilla"] for e in elegidos).most_common():
        print("   %-24s %d" % (s, c))
    print("\n   -> %s" % ruta)
    print("\n   Extraelo con:")
    print("      python ig/scrappingData_ig.py --csv ig/control/candidatos_piloto.csv")
    print("   Cuesta ~%.0f h. Luego:" % (len(elegidos) * 4 / 60.0))
    print("      python ig/control/piloto.py --medir resultados_ig/global_XXXX.json\n")


def medir(ruta_global, objetivo=60, edad_por_semilla=False):
    """edad_por_semilla: si no hay señal de edad individual, se acepta la banda
    que implica la semilla de origen (comentar en la cuenta de una prepa implica
    15-18). Sube muchisimo el rendimiento y baja la precision de la edad: hay
    que declararlo en el articulo y validarlo a mano sobre una submuestra."""
    env = json.load(open(os.path.join(DIR, "envolvente_control.json"), encoding="utf-8"))
    datos = json.load(open(ruta_global, encoding="utf-8"))
    res = datos.get("resultados", datos if isinstance(datos, list) else [])
    n0 = len(res)
    if not n0:
        sys.exit("Ese global no tiene resultados.")

    lim_seg = env["seguidores"]["limite_admision"]
    lim_pos = env["posts_totales"]["limite_admision"]
    bandas_semilla = {}
    _rc = os.path.join(DIR, "candidatos.csv")
    if os.path.exists(_rc):
        bandas_semilla = {c["usuario"].lower(): c.get("banda_esperada", "")
                          for c in csv.DictReader(open(_rc, encoding="utf-8-sig"))}

    publicos = [r for r in res if r.get("estado_cuenta") == "publica_con_posts"]
    # Cuentas profesionales: Instagram pone su categoria al principio de la bio
    # ("Digital creator", "Restaurant", "Doctor"). No son particulares.
    personales = [r for r in publicos if not categoria_profesional(r.get("biografia", ""))]
    profesionales = [r for r in publicos if categoria_profesional(r.get("biografia", ""))]
    con_edad, en_envolvente = [], []
    for r in personales:
        posts = r.get("posts_data") or []
        fechas = sorted(p["fecha"] for p in posts if p.get("fecha"))
        e = ie.inferir(bio=r.get("biografia", ""), nombre=r.get("nombre", ""),
                       usuario=r.get("usuario", ""),
                       captions=[p.get("caption", "") for p in posts][:40],
                       fecha_primer_post=fechas[0] if fechas else None)
        ok = ie.en_rango_estudio(e)
        if not ok and edad_por_semilla:
            banda = bandas_semilla.get((r.get("usuario") or "").lower(), "")
            ok = banda in ("15-17", "18-21", "15-21")
        if not ok:
            continue
        con_edad.append(r)
        seg = numero(r.get("followers"))
        if lim_seg[0] <= seg <= lim_seg[1] and lim_pos[0] <= len(posts) <= lim_pos[1]:
            en_envolvente.append(r)

    from collections import Counter
    print("\nRENDIMIENTO REAL DEL EMBUDO  (piloto de %d perfiles)\n" % n0)
    print("   estado de las cuentas: %s" % dict(Counter(r.get("estado_cuenta") for r in res)))
    etapas = [("perfiles extraidos", n0),
              ("publicos con publicaciones", len(publicos)),
              ("cuentas personales (no marca)", len(personales)),
              ("con edad usable en 15-29" + (" (o banda de semilla)" if edad_por_semilla else ""), len(con_edad)),
              ("dentro de la envolvente", len(en_envolvente))]
    prev = n0
    for nombre, n in etapas:
        print("   %-30s %4d   (%3.0f%% del paso anterior, %3.0f%% del total)"
              % (nombre, n, 100.0 * n / max(1, prev), 100.0 * n / n0))
        prev = max(1, n)

    tasa = len(en_envolvente) / n0
    if profesionales:
        from collections import Counter as _C
        print("\n   Descartadas por categoria profesional (%d): %s"
              % (len(profesionales),
                 dict(_C(categoria_profesional(r.get("biografia", "")) for r in profesionales))))
    print("\n   TASA GLOBAL: %.1f%% de los perfiles extraidos sirve como control." % (100 * tasa))
    if not en_envolvente:
        print("\n   Ningun perfil paso. Revisa las semillas antes de seguir: probablemente")
        print("   estan trayendo cuentas grandes o de otra banda de edad.\n")
        return
    # El emparejamiento pierde mas: no basta con que un control sea admisible,
    # tiene que caer en un estrato donde haya un caso esperando. Se descuenta un
    # 30% por eso, que es lo observado en la prueba de emparejamiento.
    necesarios = int(objetivo / (tasa * 0.70)) + 1
    print("\n   Para %d controles emparejados hacen falta ~%d candidatos extraidos"
          % (objetivo, necesarios))
    print("   (incluye un 30% de perdida en el emparejamiento por estratos vacios).")
    faltan = necesarios - n0
    if faltan > 0:
        print("   Ya tienes %d extraidos, faltan ~%d. A 4 min por perfil son ~%.0f horas mas."
              % (n0, faltan, faltan * 4 / 60.0))
        print("\n   Si la lista limpia no llega a %d, hay que añadir semillas en" % necesarios)
        print("   cosechar_candidatos.py y volver a cosechar.")
    else:
        print("   Ya tienes suficientes. Sigue con emparejar.py.")

    print("\n   Rendimiento por semilla (para saber que semillas repetir):")
    cand = {c["usuario"].lower(): c["semilla"]
            for c in csv.DictReader(open(os.path.join(DIR, "candidatos.csv"), encoding="utf-8-sig"))}
    buenos = Counter(cand.get((r.get("usuario") or "").lower(), "?") for r in en_envolvente)
    todos = Counter(cand.get((r.get("usuario") or "").lower(), "?") for r in res)
    for s in sorted(todos, key=lambda s: -buenos.get(s, 0)):
        print("      %-24s %d de %d" % (s, buenos.get(s, 0), todos[s]))
    print()


if __name__ == "__main__":
    if "--medir" in sys.argv:
        obj = int(sys.argv[sys.argv.index("--objetivo") + 1]) if "--objetivo" in sys.argv else 60
        medir(sys.argv[sys.argv.index("--medir") + 1], obj,
              "--edad-por-semilla" in sys.argv)
    elif "--n" in sys.argv:
        preparar(int(sys.argv[sys.argv.index("--n") + 1]))
    else:
        print(__doc__)
