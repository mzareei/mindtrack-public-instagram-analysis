# -*- coding: utf-8 -*-
"""
Detector de marco muestral.

La pregunta que responde: ¿cuanta de la señal que separa pacientes de controles
viene de COMO se consiguio cada grupo, y no del riesgo suicida?

Los casos llegan de un hospital psiquiatrico de Zapopan, tamizados con Columbia
y con consentimiento firmado. Los controles llegan de raspar cuentas publicas.
Son dos procesos de reclutamiento distintos y dejan huellas distintas en los
metadatos: cuantos seguidores tiene la cuenta, cada cuanto publica, a que hora,
que proporcion de video, hace cuanto que existe. Nada de eso es riesgo suicida.

El detector entrena un clasificador que SOLO ve metadatos, sin una sola palabra
de texto. Interpretacion:

    AUC <= 0.60   los grupos son comparables en forma. Adelante.
    0.60 - 0.70   hay sesgo de marco. Reportarlo y ajustar por ponderacion.
    > 0.70        el emparejamiento no funciono. El modelo de texto que entrenes
                  encima va a estar leyendo esto. Volver a emparejar.

Esta cifra va en el articulo. Es la respuesta a la objecion que cualquier revisor
de JMIR va a levantar, y es mucho mejor tenerla medida que discutirla.

Sin dependencias externas: regresion logistica y AUC en Python puro. Si hay
scikit-learn instalado tambien se puede comparar, pero no hace falta.

Uso:
    python ig/control/detector_marco.py --autoprueba
        Verifica el detector contra los propios pacientes: una particion al azar
        debe dar AUC ~0.5 y una particion por seguidores debe dar AUC ~1.0.

    python ig/control/detector_marco.py --casos resultados_ig/global_PACIENTES.json --controles resultados_ig/global_CONTROLES.json
"""

import json, math, os, sys, random, statistics as st
from datetime import datetime
from collections import defaultdict

random.seed(20260902)

# CARACTERISTICAS: solo forma de la cuenta, nunca contenido.
NOMBRES_CARACT = [
    "log_seguidores", "log_siguiendo", "ratio_seg_sig", "log_n_posts",
    "log_tasa_mes", "antiguedad_anios", "pct_video", "pct_carrusel",
    "hora_media", "dispersion_horas", "pct_con_hashtag", "pct_con_ubicacion",
    "long_media_caption", "tiene_bio",
]


def _log1p(x):
    return math.log1p(max(0.0, float(x or 0)))


def _fecha_de(p):
    """La fecha del post, venga del global crudo o de los CSV de extraccion.

    DEFECTO 9 CORREGIDO (07/09/2026). Esta funcion solo miraba `fecha`, que es
    el nombre que usa exportar_csv.py. El global del scraper guarda
    `fecha_post_iso`. Al pasarle un global crudo, TODAS las fechas salian vacias
    y en silencio: antiguedad_anios = 0, hora_media = 0, dispersion_horas = 0, y
    log_tasa_mes acababa siendo identico a log_n_posts (meses = 1). O sea, tres
    caracteristicas muertas y una duplicada, sin un solo error."""
    for campo in ("fecha", "fecha_post_iso"):
        f = p.get(campo)
        if f:
            try:
                return datetime.fromisoformat(str(f)[:19])
            except ValueError:
                pass
    return None


def _tipo_media(p):
    """El tipo de media, o deducido de lo que haya. En el global crudo
    `tipo_media` viene a None: solo se rellena al exportar a CSV."""
    t = str(p.get("tipo_media") or "").lower()
    if t and t != "none":
        return t
    if p.get("video_url") or p.get("video_local"):
        return "video/reel"
    return ""


def caracteristicas(perfil):
    """perfil: un registro de los que escribe scrappingData_ig.py, o una fila
    reconstruida desde los CSV de extraccion. Las dos formas dan lo mismo."""
    posts = [p for p in (perfil.get("posts_data") or [])
             if p.get("es_del_perfil", True) in (True, "si", "True")]
    fechas = [f for f in (_fecha_de(p) for p in posts) if f]
    fechas.sort()
    n = len(posts)
    # Piso de 3 meses, igual que emparejar.py: 3 posts en una semana no son
    # "12 al mes".
    meses = max(3.0, (fechas[-1] - fechas[0]).days / 30.44) if len(fechas) > 1 else 3.0
    horas = [f.hour for f in fechas]
    caps = [(p.get("caption") or "") for p in posts]
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from util import numero as _num
    seg = float(_num(perfil.get("followers")))
    sig = float(_num(perfil.get("following")))

    def pct(cond):
        return (100.0 * sum(1 for p in posts if cond(p)) / n) if n else 0.0

    return [
        _log1p(seg),
        _log1p(sig),
        seg / sig if sig else 0.0,
        _log1p(n),
        _log1p(n / meses),
        (datetime.now() - fechas[0]).days / 365.25 if fechas else 0.0,
        pct(lambda p: "video" in _tipo_media(p)),
        pct(lambda p: "carrusel" in _tipo_media(p)),
        st.mean(horas) if horas else 0.0,
        st.pstdev(horas) if len(horas) > 1 else 0.0,
        pct(lambda p: p.get("hashtags")),      # str o lista, ambas cuentan
        pct(lambda p: p.get("ubicacion")),
        st.mean([len(c.split()) for c in caps]) if caps else 0.0,
        1.0 if (perfil.get("biografia") or "").strip() else 0.0,
    ]


# REGRESION LOGISTICA (Python puro)

def _estandarizar(X):
    cols = list(zip(*X))
    mu = [st.mean(c) for c in cols]
    sd = [st.pstdev(c) or 1.0 for c in cols]
    return [[(v - m) / s for v, m, s in zip(f, mu, sd)] for f in X], mu, sd


def _aplicar(X, mu, sd):
    return [[(v - m) / s for v, m, s in zip(f, mu, sd)] for f in X]


def entrenar(X, y, iters=3000, lr=0.1, l2=1.0):
    n, d = len(X), len(X[0])
    w, b = [0.0] * d, 0.0
    for _ in range(iters):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-35, min(35, z))))
            e = p - yi
            gb += e
            for j in range(d):
                gw[j] += e * xi[j]
        b -= lr * gb / n
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
    return w, b


def predecir(X, w, b):
    out = []
    for xi in X:
        z = b + sum(wj * xj for wj, xj in zip(w, xi))
        out.append(1.0 / (1.0 + math.exp(-max(-35, min(35, z)))))
    return out


def auc(y, p):
    pares = sorted(zip(p, y))
    rangos, i = {}, 0
    while i < len(pares):
        j = i
        while j + 1 < len(pares) and pares[j + 1][0] == pares[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            rangos[k] = r
        i = j + 1
    n1 = sum(y)
    n0 = len(y) - n1
    if not n1 or not n0:
        return float("nan")
    s1 = sum(rangos[k] for k, (_, yy) in enumerate(pares) if yy == 1)
    return (s1 - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def cv_auc(X, y, k=5, repeticiones=5, semilla=20260902):
    """Validacion cruzada estratificada REPETIDA. Cada perfil es una persona, asi
    que la unidad de agrupacion ya es la persona.

    Con n pequeño (aqui 30-120 cuentas) el AUC de una sola particion se mueve
    facil +/-0.10 solo por como cayeron los pliegos. Se repite y se promedia, y
    se devuelve tambien la dispersion, para no publicar un numero que es ruido.
    Semilla fija: la misma entrada da siempre el mismo resultado."""
    rng = random.Random(semilla)
    aucs, ys_all, ps_all = [], [], []
    for _ in range(repeticiones):
        idx1 = [i for i, v in enumerate(y) if v == 1]
        idx0 = [i for i, v in enumerate(y) if v == 0]
        rng.shuffle(idx1)
        rng.shuffle(idx0)
        pliegos = [[] for _ in range(k)]
        for grupo in (idx1, idx0):
            for n, i in enumerate(grupo):
                pliegos[n % k].append(i)
        ys, ps = [], []
        for f in range(k):
            te = set(pliegos[f])
            tr = [i for i in range(len(y)) if i not in te]
            if len({y[i] for i in tr}) < 2 or not te:
                continue
            Xtr, mu, sd = _estandarizar([X[i] for i in tr])
            w, b = entrenar(Xtr, [y[i] for i in tr])
            Xte = _aplicar([X[i] for i in te], mu, sd)
            ps += predecir(Xte, w, b)
            ys += [y[i] for i in te]
        a = auc(ys, ps)
        if a == a:
            aucs.append(a)
        ys_all, ps_all = ys, ps
    media = sum(aucs) / len(aucs) if aucs else float("nan")
    disp = st.pstdev(aucs) if len(aucs) > 1 else 0.0
    return media, disp, ys_all, ps_all


def importancias(X, y):
    """AUC univariada de cada caracteristica: cual delata mas el marco."""
    out = []
    for j, nombre in enumerate(NOMBRES_CARACT):
        a = auc(y, [f[j] for f in X])
        out.append((abs(a - 0.5) + 0.5, nombre, a))
    return sorted(out, reverse=True)


def informe(X, y, etiqueta="casos vs controles"):
    a, disp, ys, ps = cv_auc(X, y)
    print("\n" + "=" * 72)
    print("DETECTOR DE MARCO MUESTRAL  (%s)" % etiqueta)
    print("=" * 72)
    print("n = %d  (%d positivos, %d negativos), %d caracteristicas, SOLO metadatos"
          % (len(y), sum(y), len(y) - sum(y), len(NOMBRES_CARACT)))
    print("\n  AUC validacion cruzada = %.3f  (DE entre repeticiones %.3f)" % (a, disp))
    if a <= 0.60:
        v = "OK. Los grupos son comparables en forma. El modelo de texto tiene sitio."
    elif a <= 0.70:
        v = "AVISO. Hay sesgo de marco. Reportarlo y ajustar por ponderacion."
    else:
        v = "ALTO. El emparejamiento no funciono. Un modelo de texto encima de esto\n        va a estar leyendo el reclutamiento, no el riesgo. Volver a emparejar."
    print("  Veredicto: %s" % v)
    print("\n  Que caracteristica delata mas (AUC univariada):")
    for _, nombre, ai in importancias(X, y)[:6]:
        print("    %-22s %.3f" % (nombre, ai))
    print()
    return a, ps


def cargar_global(ruta):
    d = json.load(open(ruta, encoding="utf-8"))
    res = d.get("resultados", d if isinstance(d, list) else [])
    return [r for r in res if r.get("estado_cuenta") == "publica_con_posts"]


def autoprueba():
    """Verifica el detector sin necesidad de tener controles todavia.

    Prueba nula   : partir a los pacientes al azar -> AUC debe rondar 0.5.
    Prueba positiva: partirlos por seguidores -> AUC debe rondar 1.0.
    Si estas dos salen, el detector mide lo que dice medir."""
    import csv
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    perf = {r["id"]: r for r in csv.DictReader(
        open(os.path.join(raiz, "resultados_ig", "extraccion", "perfiles.csv"),
             encoding="utf-8-sig")) if r["estado_cuenta"] == "publica_con_posts"}
    posts = defaultdict(list)
    for p in csv.DictReader(open(os.path.join(raiz, "resultados_ig", "extraccion", "posts.csv"),
                                 encoding="utf-8-sig")):
        if p["es_del_perfil"] == "si":
            posts[p["id"]].append(p)

    perfiles = []
    for pid, r in perf.items():
        perfiles.append({
            "id": pid, "biografia": r["biografia"],
            "followers": int(r["followers"]) if r["followers"].isdigit() else 0,
            "following": int(r["following"]) if r["following"].isdigit() else 0,
            "posts_data": [{"fecha": p["fecha"], "tipo_media": p["tipo_media"],
                            "caption": p["caption"], "hashtags": p["hashtags"],
                            "ubicacion": p["ubicacion"], "es_del_perfil": True}
                           for p in posts.get(pid, [])],
        })
    X = [caracteristicas(p) for p in perfiles]

    print("\nAUTOPRUEBA DEL DETECTOR (usando los %d pacientes publicos)" % len(X))
    y_nulo = [0] * len(X)
    for i in random.sample(range(len(X)), len(X) // 2):
        y_nulo[i] = 1
    a_nulo, _ = informe(X, y_nulo, "PRUEBA NULA: particion al azar (se espera ~0.5)")

    med = st.median([p["followers"] for p in perfiles])
    y_pos = [1 if p["followers"] > med else 0 for p in perfiles]
    a_pos, _ = informe(X, y_pos, "PRUEBA POSITIVA: partido por seguidores (se espera ~1.0)")

    ok = (0.25 <= a_nulo <= 0.75) and a_pos >= 0.85
    print("=" * 72)
    print("AUTOPRUEBA: %s   (nula=%.3f, positiva=%.3f)"
          % ("PASA" if ok else "FALLA", a_nulo, a_pos))
    print("=" * 72 + "\n")
    return ok


if __name__ == "__main__":
    if "--autoprueba" in sys.argv:
        sys.exit(0 if autoprueba() else 1)
    if "--casos" in sys.argv and "--controles" in sys.argv:
        casos = cargar_global(sys.argv[sys.argv.index("--casos") + 1])
        ctrl = cargar_global(sys.argv[sys.argv.index("--controles") + 1])
        # Por defecto solo los controles EMPAREJADOS (controles_emparejados.csv):
        # el detector mide el contraste que de verdad va a usar el modelo.
        # --todos-aprobados usa controles_evidencia.csv en su lugar.
        import csv as _csv
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "controles_evidencia.csv" if "--todos-aprobados" in sys.argv
                            else "controles_emparejados.csv")
        if os.path.exists(ruta):
            filas = list(_csv.DictReader(open(ruta, encoding="utf-8-sig")))
            usados = {(r.get("usuario") or "").lower() for r in filas if r.get("usuario")}
            ctrl = [r for r in ctrl if (r.get("usuario") or "").lower() in usados]
            print("Controles restringidos a %s: %d" % (os.path.basename(ruta), len(ctrl)))
        X = [caracteristicas(r) for r in casos] + [caracteristicas(r) for r in ctrl]
        y = [1] * len(casos) + [0] * len(ctrl)
        informe(X, y, "pacientes vs controles emparejados")
    else:
        print(__doc__)
