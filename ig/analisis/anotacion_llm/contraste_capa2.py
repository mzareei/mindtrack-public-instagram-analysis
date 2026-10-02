# -*- coding: utf-8 -*-
"""
El contraste intrasujeto sobre las categorias anotadas.

Une las etiquetas (por codigo opaco) con la clave que dice de que paciente y
ventana es cada post, agrega a paciente x ventana, y compara pericrisis contra
basal, categoria a categoria, con pruebas pareadas. Es el mismo esquema que
la capa 1 (`intra_persona.py`), aplicado a las categorias en vez de a los
rasgos de estilo.

Tres versiones del mismo contraste, y por que las tres:
  consenso   solo las etiquetas donde los dos modelos coinciden (y las
             adjudicadas por una persona, si desacuerdos.csv tiene decisiones).
             Es la principal.
  modelo A / modelo B   cada modelo por separado. Analisis de sensibilidad:
             si la conclusion cambia segun el modelo, no es una conclusion.

Unidad: proporcion de posts del paciente en la ventana que llevan la
categoria. Prueba de signos exacta + Wilcoxon pareado + FDR sobre las 8.
Ademas, el conteo agregado (cuantos posts peri vs basal llevan cada categoria)
para que se vea la magnitud cruda.

Uso como modulo desde correr_capa2.py.
"""

import csv, os, sys, statistics as st

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
ANOT = os.path.join(RAIZ, "anotacion")
SAL = os.path.join(RAIZ, "resultados_ig", "capa2")
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "estilo"))
from anotar_llm import CODIGOS
from estadistica import wilcoxon_p, signo_p, bh_fdr


def leer_clave():
    ruta = os.path.join(ANOT, "clave_anotacion.csv")
    if not os.path.exists(ruta):
        sys.exit("Falta anotacion/clave_anotacion.csv")
    return {r["codigo"]: r for r in csv.DictReader(open(ruta, encoding="utf-8-sig"))}


def etiquetas_consenso_con_adjudicacion():
    """Consenso + decisiones humanas de desacuerdos.csv si las hay."""
    cons = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(SAL, "etiquetas_consenso.csv"), encoding="utf-8-sig"))}
    ruta_d = os.path.join(SAL, "desacuerdos.csv")
    n_adj = 0
    if os.path.exists(ruta_d):
        for r in csv.DictReader(open(ruta_d, encoding="utf-8-sig")):
            k = r["codigo"]
            if k not in cons:
                continue
            for c in CODIGOS:
                v = (r.get("decision_humana_" + c) or "").strip()
                if v in ("0", "1"):
                    cons[k][c] = v
                    n_adj += 1
    return cons, n_adj


def etiquetas_modelo(proveedor):
    ruta = os.path.join(SAL, "etiquetas_%s.csv" % proveedor)
    if not os.path.exists(ruta):
        return {}
    return {r["codigo"]: r for r in csv.DictReader(open(ruta, encoding="utf-8-sig"))}


def contraste(etiquetas, clave, nombre, log=print):
    """etiquetas: codigo -> fila con las 8 categorias ('' = sin etiqueta)."""
    por_pac = {}
    for k, r in etiquetas.items():
        c = clave.get(k)
        if not c:
            continue
        pid, ven = c["id_paciente"], c["ventana"]
        d = por_pac.setdefault(pid, {"peri": [], "base": []})
        d[ven].append(r)
    pares = [(pid, d) for pid, d in por_pac.items() if d["peri"] and d["base"]]
    log("\nCONTRASTE INTRASUJETO [%s]: %d pacientes con posts etiquetados en las dos ventanas" % (nombre, len(pares)))
    filas = []
    for cat in CODIGOS:
        difs, peri_tot, base_tot, peri_n, base_n = [], 0, 0, 0, 0
        for pid, d in pares:
            p_val = [int(r[cat]) for r in d["peri"] if (r.get(cat) or "") in ("0", "1")]
            b_val = [int(r[cat]) for r in d["base"] if (r.get(cat) or "") in ("0", "1")]
            if not p_val or not b_val:
                continue
            pp, bp = sum(p_val) / float(len(p_val)), sum(b_val) / float(len(b_val))
            difs.append(pp - bp)
            peri_tot += sum(p_val); base_tot += sum(b_val); peri_n += len(p_val); base_n += len(b_val)
        sube = sum(1 for x in difs if x > 0)
        baja = sum(1 for x in difs if x < 0)
        filas.append({"categoria": cat, "n_pacientes": len(difs), "sube": sube, "baja": baja, "igual": len(difs) - sube - baja,
                      "mediana_dif": st.median(difs) if difs else float("nan"),
                      "posts_peri": "%d/%d" % (peri_tot, peri_n), "posts_base": "%d/%d" % (base_tot, base_n),
                      "pct_peri": (100.0 * peri_tot / peri_n) if peri_n else float("nan"),
                      "pct_base": (100.0 * base_tot / base_n) if base_n else float("nan"),
                      "p_signo": signo_p(sube, baja), "p_wilcoxon": wilcoxon_p(difs)})
    qs = bh_fdr([f["p_wilcoxon"] for f in filas])
    for f, q in zip(filas, qs):
        f["q_fdr"] = q
    filas.sort(key=lambda f: (f["p_wilcoxon"] if f["p_wilcoxon"] == f["p_wilcoxon"] else 9))
    log("  %-20s %3s %5s %5s %9s %9s %9s %9s %8s" % ("categoria", "n", "sube", "baja", "peri", "basal", "p signo", "p Wilcox", "q FDR"))
    for f in filas:
        marca = "  <-- q<0.05" if (f["q_fdr"] == f["q_fdr"] and f["q_fdr"] < 0.05) else ("  (p<0.05)" if f["p_wilcoxon"] == f["p_wilcoxon"] and f["p_wilcoxon"] < 0.05 else "")
        log("  %-20s %3d %5d %5d %9s %9s %9.3f %9.3f %8.3f%s" % (f["categoria"], f["n_pacientes"], f["sube"], f["baja"],
            f["posts_peri"], f["posts_base"], f["p_signo"], f["p_wilcoxon"], f["q_fdr"], marca))
    return {"nombre": nombre, "n_pacientes": len(pares), "filas": filas}


def correr(log=print, proveedores=("anthropic", "openai")):
    clave = leer_clave()
    cons, n_adj = etiquetas_consenso_con_adjudicacion()
    faltan = sum(1 for r in cons.values() for c in CODIGOS if (r.get(c) or "") not in ("0", "1"))
    log("\n  etiquetas de consenso: %d posts; celdas adjudicadas a mano: %d; celdas aun vacias: %d" % (len(cons), n_adj, faltan))
    res = [contraste(cons, clave, "consenso" + (" + adjudicacion" if n_adj else ""), log=log)]
    for p in proveedores:
        et = etiquetas_modelo(p)
        if et:
            res.append(contraste(et, clave, "solo " + p, log=log))
    with open(os.path.join(SAL, "contraste_capa2.csv"), "w", encoding="utf-8-sig", newline="") as f:
        campos = ["version", "categoria", "n_pacientes", "sube", "baja", "igual", "mediana_dif", "posts_peri", "posts_base",
                  "pct_peri", "pct_base", "p_signo", "p_wilcoxon", "q_fdr"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for r in res:
            for fila in r["filas"]:
                fila2 = {"version": r["nombre"]}
                fila2.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in fila.items()})
                w.writerow(fila2)
    return res, n_adj, faltan


if __name__ == "__main__":
    correr()
