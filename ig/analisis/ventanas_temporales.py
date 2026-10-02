# -*- coding: utf-8 -*-
"""
Diseño intrasujeto: ventanas temporales alrededor del contacto hospitalario.

La idea. Cada paciente entro al estudio en el hospital, durante un episodio de
riesgo. `fecha_consentimiento` es, con dias de margen, la fecha de ese episodio.
Eso da un ancla temporal dentro de cada persona: sus posts de las semanas
alrededor del episodio contra sus propios posts de un año antes.

Por que importa. Un contraste dentro de la misma persona controla de golpe todo
lo que un grupo control externo tiene que emparejar a mano: edad, sexo, ciudad,
escolaridad, estilo de escritura, tamaño de la cuenta, epoca de la plataforma.
No hay marco muestral que confunda, porque solo hay un marco.

Lo que este script calcula, sin anotar una sola palabra:
  1. Cuantos posts cae en cada ventana, por paciente.
  2. Si el RITMO de publicacion cambia cerca del episodio (prueba de signos
     pareada). Es la hipotesis barata: si el volumen solo ya separara, no haria
     falta texto.
  3. El presupuesto de anotacion del diseño: cuantos posts hay que etiquetar
     para poder correr el contraste, con tope por paciente.

Uso:
    python ig/analisis/ventanas_temporales.py [--ventana 90] [--tope 20]
"""

import csv, math, os, sys, statistics as st
import datetime as dt
from collections import defaultdict

# Fin de la observacion: la ultima corrida del scraper. Despues de esta fecha no
# se observo a nadie, asi que las ventanas se recortan aqui o se inflan las tasas.
FIN_OBSERVACION = dt.date(2026, 8, 28)

# Baseline: un año, terminando donde empieza la ventana pericrisis. Se recorta al
# primer post de la cuenta: no se puede contar como "no publico" un periodo en el
# que la cuenta no existia.
DIAS_BASELINE = 365

MIN_DIAS_PERI, MIN_DIAS_BASE = 30, 90


def _ruta(*p):
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, *p)


def cargar():
    sys.path.insert(0, _ruta("ig", "control"))
    from util import ruta_dataset
    c = ruta_dataset()
    if not c:
        sys.exit("No encuentro mindtrack_dataset_v1.csv. Pon MINDTRACK_DATASET=<ruta> en .env.")
    ds = {r["ID"]: r for r in csv.DictReader(open(c, encoding="utf-8-sig"))}
    posts = defaultdict(list)
    for p in csv.DictReader(open(_ruta("resultados_ig", "extraccion", "posts.csv"),
                                 encoding="utf-8-sig")):
        if p["es_del_perfil"] == "si":
            posts[p["id"]].append((dt.date.fromisoformat(p["fecha"][:10]),
                                   int(p["palabras_caption"] or 0)))
    return ds, posts


def prueba_signos(sube, baja):
    m = sube + baja
    if not m:
        return 1.0
    k = min(sube, baja)
    return min(1.0, 2 * sum(math.comb(m, i) for i in range(k + 1)) / 2 ** m)


def main():
    def arg(n, d):
        return int(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d
    VENT, TOPE = arg("--ventana", 90), arg("--tope", 20)

    ds, posts = cargar()
    print("\nVENTANAS TEMPORALES  (pericrisis = +/-%d dias del consentimiento)" % VENT)
    print("Baseline = los %d dias anteriores a la ventana pericrisis.\n" % DIAS_BASELINE)

    print("%-10s %5s %7s %8s %8s %8s" % ("ID", "edad", "n_total", "peri/mes", "base/mes", "razon"))
    print("-" * 54)
    pares, discordantes, presupuesto = [], [], 0
    for pid in sorted(posts):
        row = ds.get(pid)
        if not row or not row["fecha_consentimiento"]:
            continue
        fc = dt.date.fromisoformat(row["fecha_consentimiento"])
        fechas = sorted(f for f, _ in posts[pid])
        inicio = fechas[0]

        p0, p1 = fc - dt.timedelta(VENT), min(fc + dt.timedelta(VENT), FIN_OBSERVACION)
        b1 = p0
        b0 = max(fc - dt.timedelta(VENT + DIAS_BASELINE), inicio)
        dias_p, dias_b = (p1 - p0).days, (b1 - b0).days

        n_peri = sum(1 for f in fechas if p0 <= f <= p1)
        n_base = sum(1 for f in fechas if b0 <= f <= b1)
        if n_peri and n_base:
            discordantes.append((pid, n_peri, n_base))
            presupuesto += min(n_peri, TOPE) + min(n_base, TOPE)

        if dias_p < MIN_DIAS_PERI or dias_b < MIN_DIAS_BASE:
            continue
        rp, rb = n_peri / (dias_p / 30.44), n_base / (dias_b / 30.44)
        if not rp and not rb:
            continue
        razon = (rp + 0.01) / (rb + 0.01)
        pares.append((pid, rp, rb, razon))
        print("%-10s %5s %7d %8.2f %8.2f %8.2f"
              % (pid, row["edad"], len(fechas), rp, rb, razon))

    print("-" * 54)
    sube = sum(1 for _, rp, rb, _ in pares if rp > rb)
    baja = sum(1 for _, rp, rb, _ in pares if rp < rb)
    p = prueba_signos(sube, baja)
    geo = math.exp(st.mean([math.log(r) for *_, r in pares])) if pares else float("nan")

    print("\n1) ¿CAMBIA EL RITMO DE PUBLICACION CERCA DEL EPISODIO?")
    print("   n con exposicion suficiente : %d" % len(pares))
    print("   sube en %d, baja en %d" % (sube, baja))
    print("   prueba de signos pareada    : p = %.3f" % p)
    print("   razon geometrica peri/base  : %.2f" % geo)
    if p > 0.05:
        print("   -> No hay señal en el VOLUMEN. Publicar mas o menos no distingue el")
        print("      episodio. Si hay señal, esta en el contenido, y la unica forma de")
        print("      llegar a ella es anotar. Esto tambien acota al grupo control: si")
        print("      el ritmo no separa el episodio DENTRO de la misma persona, un AUC")
        print("      alto sacado de metadatos ENTRE personas es marco muestral, no riesgo.")
    else:
        print("   -> Hay señal en el volumen. Reportarla y controlarla antes de atribuir")
        print("      nada al texto.")

    print("\n2) PRESUPUESTO DE ANOTACION DEL DISEÑO")
    print("   pacientes discordantes (con ambas ventanas) : %d de %d"
          % (len(discordantes), len(posts)))
    total_bruto = sum(a + b for _, a, b in discordantes)
    print("   posts en ambas ventanas, sin tope           : %d" % total_bruto)
    print("   con tope de %d posts por paciente y ventana  : %d" % (TOPE, presupuesto))
    print("   (el corpus completo son %d posts: el diseño intrasujeto necesita"
          % sum(len(v) for v in posts.values()))
    print("    anotar el %d%% de el para dar su primera respuesta)"
          % round(100.0 * presupuesto / max(1, sum(len(v) for v in posts.values()))))

    print("\n3) CONCENTRACION")
    tam = sorted((len(v) for v in posts.values()), reverse=True)
    print("   los 4 pacientes mas activos aportan el %d%% de los posts."
          % round(100.0 * sum(tam[:4]) / sum(tam)))
    print("   -> validacion cruzada AGRUPADA POR PACIENTE, siempre. Y reportar la")
    print("      distribucion de AUC por paciente, no solo el AUC agrupado.\n")


if __name__ == "__main__":
    main()
