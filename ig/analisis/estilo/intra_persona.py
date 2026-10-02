# -*- coding: utf-8 -*-
"""
Capa 1, paso 3: dentro de la misma persona, ¿cambia el estilo cerca del episodio?

Para cada paciente con posts en las dos ventanas (pericrisis = +/-90 dias del
consentimiento; basal = los 365 dias anteriores, recortado al primer post) se
calculan los 25 rasgos sobre TODOS los posts de cada ventana (aqui no hay tope
de 20: el tope del kit de anotacion era por coste de anotador, no por diseño) y
se compara peri contra basal, rasgo a rasgo, con pruebas pareadas:

  - cuantos pacientes suben y cuantos bajan
  - prueba de signos exacta
  - Wilcoxon de rangos con signo (aprox. normal; n~18)
  - mediana de la diferencia peri - basal
  - FDR de Benjamini-Hochberg sobre los 25 Wilcoxon

Se reporta todo, no solo lo significativo, y la direccion en cada paciente:
con 18 personas, "sube en 14 de 18" dice mas que un p-valor.

Uso como modulo desde correr_capa1.py.
"""

import os, sys, statistics as st
import datetime as dt

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(DIR)), "control"))
from rasgos import NOMBRES, rasgos_de_posts
from estadistica import wilcoxon_p, signo_p, bh_fdr
from ventanas_temporales import FIN_OBSERVACION, DIAS_BASELINE


def ventanas(posts, fecha_consentimiento, vent=90):
    """Devuelve (peri, base) como listas de posts, o (None, None) si no hay
    posts en ambas."""
    fc = fecha_consentimiento
    con_fecha = []
    for p in posts:
        f = p.get("fecha_post_iso") or p.get("fecha") or ""
        try:
            con_fecha.append((dt.date.fromisoformat(str(f)[:10]), p))
        except ValueError:
            continue
    if not con_fecha:
        return None, None
    inicio = min(f for f, _ in con_fecha)
    p0, p1 = fc - dt.timedelta(vent), min(fc + dt.timedelta(vent), FIN_OBSERVACION)
    b1, b0 = p0, max(fc - dt.timedelta(vent + DIAS_BASELINE), inicio)
    peri = [p for f, p in con_fecha if p0 <= f <= p1]
    base = [p for f, p in con_fecha if b0 <= f <= b1]
    if not peri or not base:
        return None, None
    return peri, base


def correr(pacientes, consentimientos, vent=90, log=print):
    """pacientes: lista de perfiles del global (con posts_data, es_del_perfil
    True). consentimientos: dict id -> date."""
    pares = []
    for perf in pacientes:
        pid = perf.get("id")
        fc = consentimientos.get(pid)
        if not fc:
            continue
        posts = [p for p in (perf.get("posts_data") or []) if str(p.get("es_del_perfil", "True")) in ("True", "si", "1")]
        peri, base = ventanas(posts, fc, vent)
        if peri is None:
            continue
        pares.append((pid, len(peri), len(base), rasgos_de_posts(peri), rasgos_de_posts(base)))
    log("\nINTRA PERSONA: %d pacientes con posts en las dos ventanas (peri +/-%d d, basal %d d)"
        % (len(pares), vent, DIAS_BASELINE))
    log("  posts: peri %d, basal %d" % (sum(a for _, a, _, _, _ in pares), sum(b for _, _, b, _, _ in pares)))
    filas = []
    for n in NOMBRES:
        difs, ids = [], []
        for pid, _, _, rp, rb in pares:
            a, b = rp.get(n), rb.get(n)
            if a is None or b is None or a != a or b != b:
                continue
            difs.append(a - b)
            ids.append(pid)
        sube = sum(1 for d in difs if d > 0)
        baja = sum(1 for d in difs if d < 0)
        filas.append({"rasgo": n, "n": len(difs), "sube": sube, "baja": baja,
                      "igual": len(difs) - sube - baja,
                      "mediana_dif": st.median(difs) if difs else float("nan"),
                      "p_signo": signo_p(sube, baja),
                      "p_wilcoxon": wilcoxon_p(difs)})
    qs = bh_fdr([f["p_wilcoxon"] for f in filas])
    for f, q in zip(filas, qs):
        f["q_fdr"] = q
    filas.sort(key=lambda f: (f["p_wilcoxon"] if f["p_wilcoxon"] == f["p_wilcoxon"] else 9))
    log("\n  %-16s %3s %5s %5s %12s %9s %9s %8s" % ("rasgo", "n", "sube", "baja", "med(peri-bas)", "p signo", "p Wilcox", "q FDR"))
    for f in filas:
        marca = "  <-- q<0.05" if f["q_fdr"] == f["q_fdr"] and f["q_fdr"] < 0.05 else ("  (p<0.05)" if f["p_wilcoxon"] < 0.05 else "")
        log("  %-16s %3d %5d %5d %12.3f %9.3f %9.3f %8.3f%s" % (
            f["rasgo"], f["n"], f["sube"], f["baja"], f["mediana_dif"], f["p_signo"], f["p_wilcoxon"], f["q_fdr"], marca))
    return {"n_pacientes": len(pares), "filas": filas,
            "por_paciente": [(pid, np, nb) for pid, np, nb, _, _ in pares]}
