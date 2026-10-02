# -*- coding: utf-8 -*-
"""
Envolvente de emparejamiento: describe COMO son las cuentas de los pacientes,
para poder exigirle lo mismo a las cuentas control.

Por que existe este script. El riesgo central de un grupo control sacado de
Instagram publico no es la edad: es que las cuentas publicas que se pueden
raspar son, por construccion, de gente que publica para una audiencia. Los
pacientes tienen cuentas chicas, cerradas y poco activas. Si no se acota, el
clasificador de texto aprende "cuenta grande vs cuenta chica" y da AUC alta sin
significar nada.

Este script saca del propio dataset de pacientes los percentiles que definen la
envolvente, y los escribe en envolvente_control.json para que emparejar.py los
aplique. Se recalcula cada vez que crece la muestra de pacientes, no se
hardcodea.

Uso:
    python ig/control/envolvente.py
"""

import csv, json, os, sys, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import numero
from datetime import datetime
from collections import Counter, defaultdict


def _ruta(*p):
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, *p)


def _buscar_dataset():
    for c in (_ruta("mindtrack_dataset_v1.csv"),
              _ruta("..", "Rio Arronte", "Modelo IA", "mindtrack_dataset_v1.csv")):
        if os.path.exists(c):
            return c
    return None


def percentil(valores, p):
    v = sorted(valores)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def construir(ruta_dataset=None, salida=None):
    ruta_dataset = ruta_dataset or _buscar_dataset()
    if not ruta_dataset:
        sys.exit("No encuentro mindtrack_dataset_v1.csv. Pasa la ruta como argumento.")
    salida = salida or _ruta("ig", "control", "envolvente_control.json")

    ds = {r["ID"]: r for r in csv.DictReader(open(ruta_dataset, encoding="utf-8-sig"))}
    perf = [r for r in csv.DictReader(open(_ruta("resultados_ig", "extraccion", "perfiles.csv"),
                                          encoding="utf-8-sig"))
            if r["estado_cuenta"] == "publica_con_posts"]
    posts = [p for p in csv.DictReader(open(_ruta("resultados_ig", "extraccion", "posts.csv"),
                                            encoding="utf-8-sig"))
             if p["es_del_perfil"] == "si"]

    fechas = defaultdict(list)
    for p in posts:
        fechas[p["id"]].append(datetime.fromisoformat(p["fecha"]).date())

    def num(r, campo):
        """numero(), no isdigit(). Instagram escribe "1,180" y "158K", que no
        son digitos: con isdigit() esos perfiles se caian en silencio del
        calculo. La envolvente del 02/09 se hizo con 24 de 30 pacientes, y los
        6 que faltaban eran justo los de mas seguidores, asi que el techo salio
        demasiado bajo."""
        v = numero(r.get(campo), None)
        return v

    followers = [num(r, "followers") for r in perf]
    followers = [x for x in followers if x is not None]
    following = [num(r, "following") for r in perf]
    following = [x for x in following if x is not None]
    n_posts = [num(r, "posts_ig") for r in perf]
    n_posts = [x for x in n_posts if x is not None]

    tasas = []
    for r in perf:
        f = sorted(fechas.get(r["id"], []))
        if len(f) < 2:
            continue
        meses = max(3.0, (f[-1] - f[0]).days / 30.44)   # piso de 3 meses, igual que emparejar.py
        tasas.append(len(f) / meses)

    edades = [int(ds[r["id"]]["edad"]) for r in perf
              if r["id"] in ds and ds[r["id"]]["edad"].isdigit()]
    generos = Counter(ds[r["id"]]["genero"] for r in perf if r["id"] in ds)
    tipos = Counter(p["tipo_media"] for p in posts)
    total_tipos = sum(tipos.values()) or 1

    env = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "n_pacientes_publicos_con_posts": len(perf),
        "n_posts": len(posts),
        "edad": {
            "n": len(edades), "min": min(edades), "max": max(edades),
            "media": round(st.mean(edades), 1), "mediana": st.median(edades),
            "distribucion_bandas": dict(Counter(
                next("%d-%d" % (lo, hi) for lo, hi in ((15, 17), (18, 21), (22, 25), (26, 29))
                     if lo <= e <= hi) for e in edades)),
        },
        "genero": dict(generos),
        # Los limites duros de admision son el RANGO OBSERVADO en los pacientes
        # con 50% de holgura por arriba. Cortar en p25-p75 dejaria fuera
        # controles legitimos; dejarlo abierto mete cuentas de creador de
        # contenido, que es exactamente el confusor que hay que evitar. El
        # emparejamiento fino lo hace despues emparejar.py.
        "seguidores": {
            "n": len(followers), "min": min(followers), "max": max(followers),
            "p25": percentil(followers, .25), "mediana": st.median(followers),
            "p75": percentil(followers, .75),
            # Tope por p90 x 1.5, no por el maximo. MINDxxxx es creadora de
            # contenido con 57,300 seguidores, 26 veces el siguiente paciente
            # (2,218). Con max x 1.5 el techo se iba a 85,950 y dejaba entrar
            # cuentas de creador al grupo control, que es justo el confusor que
            # toda esta envolvente existe para evitar. El outlier se declara
            # como limitacion, no se usa para fijar el limite.
            "limite_admision": [max(0, int(min(followers) * 0.5)),
                                int(percentil(followers, .90) * 1.5)],
            "outlier_declarado": max(followers),
        },
        "siguiendo": {
            "n": len(following), "mediana": st.median(following),
            "p25": percentil(following, .25), "p75": percentil(following, .75),
        },
        "posts_totales": {
            "n": len(n_posts), "min": min(n_posts), "max": max(n_posts),
            "p25": percentil(n_posts, .25), "mediana": st.median(n_posts),
            "p75": percentil(n_posts, .75),
            "limite_admision": [1, int(max(n_posts) * 1.5)],
        },
        "tasa_posts_mes": {
            "n": len(tasas), "mediana": round(st.median(tasas), 2),
            "p25": round(percentil(tasas, .25), 2), "p75": round(percentil(tasas, .75), 2),
            "limite_admision": [0.0, round(max(tasas) * 1.5, 2)],
        },
        "mezcla_media": {k: round(v / total_tipos, 3) for k, v in tipos.items()},
        "bio_no_vacia_pct": round(100.0 * sum(1 for r in perf if r["biografia"].strip()) / len(perf)),
    }

    # Concentracion: cuanto del corpus aportan los mayores publicadores. Si un
    # puñado de personas domina, el modelo a nivel de post modela a esas personas.
    por_persona = sorted((len(v) for v in fechas.values()), reverse=True)
    env["concentracion"] = {
        "top4_pct_de_posts": round(100.0 * sum(por_persona[:4]) / max(1, sum(por_persona))),
        "posts_por_paciente_mediana": st.median(por_persona),
    }

    json.dump(env, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\nENVOLVENTE DE EMPAREJAMIENTO  (derivada de %d pacientes, %d posts)\n"
          % (env["n_pacientes_publicos_con_posts"], env["n_posts"]))
    print("  edad            %d-%d  (mediana %s, media %s)" % (
        env["edad"]["min"], env["edad"]["max"], env["edad"]["mediana"], env["edad"]["media"]))
    print("  bandas          %s" % env["edad"]["distribucion_bandas"])
    print("  genero          %s" % env["genero"])
    print("  seguidores      mediana %s   p25-p75 %s-%s   ADMISION %s" % (
        env["seguidores"]["mediana"], env["seguidores"]["p25"], env["seguidores"]["p75"],
        env["seguidores"]["limite_admision"]))
    print("  posts totales   mediana %s   p25-p75 %s-%s   ADMISION %s" % (
        env["posts_totales"]["mediana"], env["posts_totales"]["p25"],
        env["posts_totales"]["p75"], env["posts_totales"]["limite_admision"]))
    print("  posts/mes       mediana %s   p25-p75 %s-%s   ADMISION %s" % (
        env["tasa_posts_mes"]["mediana"], env["tasa_posts_mes"]["p25"],
        env["tasa_posts_mes"]["p75"], env["tasa_posts_mes"]["limite_admision"]))
    print("  mezcla media    %s" % env["mezcla_media"])
    print("  bio no vacia    %d%%" % env["bio_no_vacia_pct"])
    print("\n  ATENCION concentracion: los 4 pacientes mas activos aportan el %d%%"
          % env["concentracion"]["top4_pct_de_posts"])
    print("  de los posts (mediana por paciente: %s). Cualquier modelo a nivel de"
          % env["concentracion"]["posts_por_paciente_mediana"])
    print("  post tiene que agrupar por paciente en la validacion cruzada o va a")
    print("  estar midiendo a esas 4 personas.")
    print("\n  -> %s\n" % salida)
    return env


if __name__ == "__main__":
    construir(sys.argv[1] if len(sys.argv) > 1 else None)
