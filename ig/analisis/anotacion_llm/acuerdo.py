# -*- coding: utf-8 -*-
"""
Acuerdo entre los dos modelos, y la cola de adjudicacion humana.

Para cada categoria:
  - prevalencia segun cada modelo (cuantos posts la llevan)
  - acuerdo bruto (% de posts donde coinciden)
  - kappa de Cohen (acuerdo corregido por azar)
  - kappa de prevalencia ajustada (PABAK), porque con categorias raras el kappa
    de Cohen sale bajo aunque coincidan en el 95% de los posts

Lectura de kappa (Landis & Koch): <0.20 pobre, 0.20-0.40 debil, 0.40-0.60
moderado, 0.60-0.80 sustancial, >0.80 casi perfecto. Umbral de trabajo: 0.60.
Una categoria por debajo no se tira: se reporta con su kappa y se excluye del
contraste principal o se fusiona.

Produce:
  acuerdo.csv                 la tabla de arriba
  desacuerdos.csv             UN post por fila con las categorias en que no
                              coinciden, el texto, la imagen y las dos
                              justificaciones: la cola para que una persona
                              decida. Columna `decision_humana_<cat>` vacia.
  muestra_validez.csv         20% al azar (semilla fija) de los posts donde
                              los dos coinciden, para que una persona compruebe
                              que "coinciden" no significa "coinciden en el
                              error". Misma estructura.
  etiquetas_consenso.csv      donde coinciden, la etiqueta; donde no, vacio
                              hasta que se adjudique. Es la entrada del
                              contraste.

Uso como modulo desde correr_capa2.py, o suelto:
    python ig/analisis/anotacion_llm/acuerdo.py
"""

import csv, os, random, sys

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
ANOT = os.path.join(RAIZ, "anotacion")
SAL = os.path.join(RAIZ, "resultados_ig", "capa2")
sys.path.insert(0, DIR)
from anotar_llm import CODIGOS


def leer_etiquetas(proveedor):
    ruta = os.path.join(SAL, "etiquetas_%s.csv" % proveedor)
    if not os.path.exists(ruta):
        return {}
    return {r["codigo"]: r for r in csv.DictReader(open(ruta, encoding="utf-8-sig"))}


def kappa(a, b):
    """Cohen. a, b listas de 0/1 de igual longitud."""
    n = len(a)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / float(n)
    pa1 = sum(a) / float(n)
    pb1 = sum(b) / float(n)
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    k = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    pabak = 2 * po - 1
    return po, k, pabak


def calificar(k):
    if k != k:
        return "n/a"
    if k < 0.20:
        return "pobre"
    if k < 0.40:
        return "debil"
    if k < 0.60:
        return "moderado"
    if k < 0.80:
        return "sustancial"
    return "casi perfecto"


def correr(log=print, proveedores=("anthropic", "openai")):
    A = leer_etiquetas(proveedores[0])
    B = leer_etiquetas(proveedores[1])
    comunes = sorted(set(A) & set(B))
    if not comunes:
        sys.exit("No hay etiquetas de los dos modelos. Corre antes anotar_llm.py")
    corpus = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(ANOT, "corpus_anotacion.csv"), encoding="utf-8-sig"))}
    log("\nACUERDO ENTRE MODELOS: %s vs %s, %d publicaciones" % (proveedores[0], proveedores[1], len(comunes)))
    log("  %-20s %7s %7s %8s %7s %7s  %s" % ("categoria", "prev.A", "prev.B", "acuerdo", "kappa", "PABAK", ""))
    tabla = []
    for c in CODIGOS:
        a = [int(A[k][c] or 0) for k in comunes]
        b = [int(B[k][c] or 0) for k in comunes]
        po, k, pab = kappa(a, b)
        fila = {"categoria": c, "n": len(comunes), "prevalencia_A": sum(a), "prevalencia_B": sum(b),
                "acuerdo_bruto": round(po, 3), "kappa": round(k, 3) if k == k else "", "pabak": round(pab, 3),
                "calificacion": calificar(k), "usable": "si" if (k == k and k >= 0.60) or pab >= 0.60 else "revisar"}
        tabla.append(fila)
        log("  %-20s %7d %7d %7.0f%% %7s %7.3f  %s" % (c, sum(a), sum(b), 100 * po, ("%.3f" % k) if k == k else "n/a", pab, fila["calificacion"]))
    # orientacion temporal y confianza: acuerdo bruto nada mas
    ot = sum(1 for k in comunes if (A[k].get("orientacion_temporal") or "") == (B[k].get("orientacion_temporal") or "")) / float(len(comunes))
    log("  %-20s %23s %7.0f%%" % ("orientacion_temporal", "", 100 * ot))

    os.makedirs(SAL, exist_ok=True)
    with open(os.path.join(SAL, "acuerdo.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tabla[0].keys()))
        w.writeheader()
        w.writerows(tabla)

    # desacuerdos y consenso
    desac, consenso = [], []
    for k in comunes:
        difs = [c for c in CODIGOS if int(A[k][c] or 0) != int(B[k][c] or 0)]
        fila_c = {"codigo": k}
        for c in CODIGOS:
            fila_c[c] = A[k][c] if c not in difs else ""
        fila_c["pendiente_adjudicar"] = ",".join(difs)
        consenso.append(fila_c)
        if difs:
            d = {"codigo": k, "categorias_en_desacuerdo": ",".join(difs),
                 "texto": corpus.get(k, {}).get("texto", ""), "imagen": corpus.get(k, {}).get("imagen", "")}
            for c in CODIGOS:
                d["A_" + c] = A[k][c]
                d["B_" + c] = B[k][c]
            d["A_justificacion"] = A[k].get("justificacion", "")
            d["B_justificacion"] = B[k].get("justificacion", "")
            for c in difs:
                d["decision_humana_" + c] = ""
            desac.append(d)
    campos_d = ["codigo", "categorias_en_desacuerdo", "texto", "imagen"] + ["A_" + c for c in CODIGOS] + ["B_" + c for c in CODIGOS] + \
               ["A_justificacion", "B_justificacion"] + ["decision_humana_" + c for c in CODIGOS]
    with open(os.path.join(SAL, "desacuerdos.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos_d, extrasaction="ignore")
        w.writeheader()
        w.writerows(desac)
    with open(os.path.join(SAL, "etiquetas_consenso.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["codigo"] + CODIGOS + ["pendiente_adjudicar"])
        w.writeheader()
        w.writerows(consenso)

    # muestra de validez: 20% de los que coinciden en todo
    coinciden = [k for k in comunes if not any(int(A[k][c] or 0) != int(B[k][c] or 0) for c in CODIGOS)]
    rng = random.Random(20260910)
    muestra = sorted(rng.sample(coinciden, max(1, int(round(0.20 * len(coinciden))))) if coinciden else [])
    with open(os.path.join(SAL, "muestra_validez.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "texto", "imagen"] + ["modelos_" + c for c in CODIGOS] + ["humano_" + c for c in CODIGOS] + ["notas"])
        for k in muestra:
            w.writerow([k, corpus.get(k, {}).get("texto", ""), corpus.get(k, {}).get("imagen", "")] +
                       [A[k][c] for c in CODIGOS] + [""] * len(CODIGOS) + [""])

    n_total_desac = len(desac)
    n_celdas = sum(len(d["categorias_en_desacuerdo"].split(",")) for d in desac)
    log("\n  posts donde coinciden en todo : %d de %d" % (len(coinciden), len(comunes)))
    log("  posts con algun desacuerdo    : %d  (%d decisiones humanas en total)" % (n_total_desac, n_celdas))
    log("  muestra de validez (20%% de los coincidentes): %d posts" % len(muestra))
    log("  -> resultados_ig/capa2/acuerdo.csv, desacuerdos.csv, muestra_validez.csv, etiquetas_consenso.csv")
    return {"tabla": tabla, "n": len(comunes), "coinciden": len(coinciden), "desacuerdos": n_total_desac,
            "decisiones": n_celdas, "validez": len(muestra), "ot_acuerdo": ot}


if __name__ == "__main__":
    correr()
