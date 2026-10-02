# -*- coding: utf-8 -*-
"""
Manuscript analysis 5: sensitivity analyses requested by internal review.

  A. Sampling-frame detector BEFORE matching: patients vs (i) all extracted
     public candidates and (ii) the eligible pool with age evidence (after
     manual discards), to show what matching removed; the post-matching AUC is
     a check of matching, not a finding.
  B. Between-person AUCs excluding the 18 controls drawn from a neighbouring
     stratum; excluding the 4 most active patients; style restricted to
     accounts with at least one word (no imputation of lexical features).
  C. Union labels ("either rater positive") for the layer 2 contrast, the
     anticonservative counterpart of the consensus analysis.
  D. Bootstrap CI of the geometric mean peri/baseline posting-rate ratio for
     each window width; observed post-contact exposure.

Outputs: resultados_ig/manuscrito/sensibilidad.json and CSVs.
"""
import csv, json, math, os, sys, statistics as st
import datetime as dt
from collections import defaultdict
import numpy as np
from scipy import stats

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
RES = os.path.join(RAIZ, "resultados_ig")
SAL = os.path.join(RES, "manuscrito")
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.join(RAIZ, "ig", "control"))
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "estilo"))
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "anotacion_llm"))
from cvlib import cv_scores, auc_np, bootstrap_auc, delong_ci
import detector_marco as dm
from rasgos import NOMBRES
from entre_personas import imputar
from estadistica import wilcoxon_p, signo_p
from anotar_llm import CODIGOS
from util import es_no_persona

out = {}


def resumen_auc(nombre, X, y):
    aucs, S = cv_scores(X, y, repeticiones=20)
    bag = np.nanmean(S, axis=0)
    a = auc_np(y, bag); lo, hi = bootstrap_auc(y, bag)
    r = {"analysis": nombre, "n_patients": int(sum(y)), "n_controls": int(len(y) - sum(y)), "features": len(X[0]),
         "auc_cv_mean": round(float(aucs.mean()), 3), "auc_cv_sd": round(float(aucs.std()), 3), "auc_bagged": round(a, 3), "boot95": "%.3f-%.3f" % (lo, hi)}
    print("  %-70s n=%d/%d  AUC %.3f (SD %.3f)  bagged %.3f  95%% CI %.3f-%.3f" % (nombre, sum(y), len(y) - sum(y), aucs.mean(), aucs.std(), a, lo, hi))
    return r


# ---------------------------------------------------------------------------
print("A. FRAME DETECTOR BEFORE MATCHING")
pac = dm.cargar_global(os.path.join(RES, "global_20260828_163758.json"))
ctrl_all = dm.cargar_global(os.path.join(RES, "global_controles_unido_20260909_150153.json"))
emp = list(csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "controles_emparejados.csv"), encoding="utf-8-sig")))
usados = {r["usuario"].lower() for r in emp}
vecino = {r["usuario"].lower() for r in emp if r["estrato_relajado"] == "si"}
ev = {r["usuario"].lower() for r in csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "controles_evidencia.csv"), encoding="utf-8-sig"))}
manual = {l.split("#")[0].strip().lower() for l in open(os.path.join(RAIZ, "ig", "control", "descartes_manuales.txt"), encoding="utf-8") if l.strip() and not l.startswith("#")}
elegibles = [r for r in ctrl_all if (r.get("usuario") or "").lower() in ev and (r.get("usuario") or "").lower() not in manual
             and not es_no_persona(r.get("nombre"), r.get("biografia"), r.get("posts_data"), (r.get("usuario") or "").lower())]
Xp = [dm.caracteristicas(r) for r in pac]
tab = []
for nombre, pool in [("all extracted public candidates (before any eligibility step)", ctrl_all),
                     ("eligible pool: verifiable age evidence, non-persons and false ages removed", elegibles),
                     ("matched controls (after envelope, strata and nearest neighbour)", [r for r in ctrl_all if (r.get("usuario") or "").lower() in usados])]:
    X = Xp + [dm.caracteristicas(r) for r in pool]; y = [1] * len(pac) + [0] * len(pool)
    tab.append(resumen_auc("metadata, patients vs " + nombre, X, y))
out["frame_before_matching"] = tab

# ---------------------------------------------------------------------------
print("\nB. BETWEEN-PERSON SENSITIVITY")
ctrl = [r for r in ctrl_all if (r.get("usuario") or "").lower() in usados]
ctrl_id = {r["usuario"].lower(): r["id_control"] for r in emp}
ids = [r["id"] for r in pac] + [ctrl_id[r["usuario"].lower()] for r in ctrl]
rc = {r["id"]: r for r in csv.DictReader(open(os.path.join(RES, "capa1", "rasgos_cuentas.csv"), encoding="utf-8-sig"))}
filas = [{n: (float(rc[i][n]) if rc[i][n] not in ("", "nan") else None) for n in NOMBRES} for i in ids]
X_style, _ = imputar(filas, NOMBRES)
X_meta = Xp + [dm.caracteristicas(r) for r in ctrl]
y = [1] * len(pac) + [0] * len(ctrl)
palabras = [int(rc[i]["n_palabras"]) for i in ids]
n_posts = [int(rc[i]["n_posts"]) for i in ids]
keep_vecino = [i for i, r in enumerate(pac + ctrl) if i < len(pac) or (r.get("usuario") or "").lower() not in vecino]
top4 = set(sorted(range(len(pac)), key=lambda i: -n_posts[i])[:4])
keep_top4 = [i for i in range(len(y)) if i not in top4]
keep_words = [i for i in range(len(y)) if palabras[i] > 0]
sens = []
for nombre, keep, X in [("metadata, excluding the 18 neighbouring-stratum controls", keep_vecino, X_meta),
                        ("style, excluding the 18 neighbouring-stratum controls", keep_vecino, X_style),
                        ("metadata, excluding the 4 most active patients", keep_top4, X_meta),
                        ("style, excluding the 4 most active patients", keep_top4, X_style),
                        ("style, accounts with at least one caption word only (no lexical imputation)", keep_words, X_style)]:
    Xk = [X[i] for i in keep]; yk = [y[i] for i in keep]
    if nombre.startswith("style, accounts with"):
        # re-impute the remaining structural gaps (emoji valence, diversity, burstiness) within the subset
        fk = [filas[i] for i in keep]; Xk, imp = imputar(fk, NOMBRES)
    sens.append(resumen_auc(nombre, Xk, yk))
out["between_person_sensitivity"] = sens
out["accounts_with_words"] = {"patients": sum(1 for i in keep_words if y[i]), "controls": sum(1 for i in keep_words if not y[i])}

# ---------------------------------------------------------------------------
print("\nC. UNION LABELS (either rater positive)")
clave = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "anotacion", "clave_anotacion.csv"), encoding="utf-8-sig"))}
ds = {r["ID"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "mindtrack_dataset_v1.csv"), encoding="utf-8-sig"))}
etq = {p: {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RES, "capa2", "etiquetas_%s.csv" % p), encoding="utf-8-sig"))} for p in ("anthropic", "openai")}
NO_SIMB = [c for c in CODIGOS if c != "expresion_simbolica"]


def contraste(valor_fn, nombre):
    por = defaultdict(lambda: {"peri": [], "base": []})
    for k, c in clave.items():
        v = valor_fn(k)
        if v is None:
            continue
        por[c["id_paciente"]][c["ventana"]].append(v)
    pares = [(p, d) for p, d in por.items() if d["peri"] and d["base"]]
    difs = [st.mean(d["peri"]) - st.mean(d["base"]) for _, d in pares]
    sube, baja = sum(1 for x in difs if x > 0), sum(1 for x in difs if x < 0)
    pk, pn = sum(sum(d["peri"]) for _, d in pares), sum(len(d["peri"]) for _, d in pares)
    bk, bn = sum(sum(d["base"]) for _, d in pares), sum(len(d["base"]) for _, d in pares)
    return {"category": nombre, "n_patients": len(pares), "up": sube, "down": baja, "tie": len(pares) - sube - baja,
            "peri": "%d/%d" % (pk, pn), "peri_pct": round(100.0 * pk / pn, 1), "baseline": "%d/%d" % (bk, bn), "base_pct": round(100.0 * bk / bn, 1),
            "peri_upper95_exact_pct": round(100.0 * stats.beta.ppf(0.975, pk + 1, pn - pk), 1),
            "patients_with_marker_peri": sum(1 for _, d in pares if sum(d["peri"])), "patients_with_marker_baseline": sum(1 for _, d in pares if sum(d["base"])),
            "p_sign": round(signo_p(sube, baja), 3) if (sube + baja) else float("nan"), "p_wilcoxon": round(wilcoxon_p(difs), 3) if wilcoxon_p(difs) == wilcoxon_p(difs) else float("nan")}


union = []
for cat in CODIGOS:
    union.append(contraste(lambda k, c=cat: 1 if (etq["anthropic"][k][c] == "1" or etq["openai"][k][c] == "1") else 0, cat))
union.append(contraste(lambda k: 1 if any(etq[p][k][c] == "1" for p in etq for c in NO_SIMB) else 0, "any of 7 distress categories"))
for r in union:
    print("  %-30s n=%d up %d down %d tie %d  peri %s (%.1f%%, upper %.1f%%)  base %s (%.1f%%)  p_sign %s  p_wilc %s" % (
        r["category"], r["n_patients"], r["up"], r["down"], r["tie"], r["peri"], r["peri_pct"], r["peri_upper95_exact_pct"], r["baseline"], r["base_pct"], r["p_sign"], r["p_wilcoxon"]))
with open(os.path.join(SAL, "contraste_union.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(union[0].keys())); w.writeheader(); w.writerows(union)
out["union_contrast"] = union

# ---------------------------------------------------------------------------
print("\nD. POSTING RATE RATIO CIs AND EXPOSURE")
posts = defaultdict(list)
for p in csv.DictReader(open(os.path.join(RES, "extraccion", "posts.csv"), encoding="utf-8-sig")):
    if p["es_del_perfil"] == "si":
        posts[p["id"]].append(dt.date.fromisoformat(p["fecha"][:10]))
FIN = dt.date(2026, 8, 28)
rng = np.random.default_rng(11)
ratios = []
for VENT in (30, 60, 90, 180):
    pares = []
    for pid, fechas in posts.items():
        row = ds.get(pid)
        if not row or not row["fecha_consentimiento"]:
            continue
        fc = dt.date.fromisoformat(row["fecha_consentimiento"]); fechas = sorted(fechas)
        p0, p1 = fc - dt.timedelta(VENT), min(fc + dt.timedelta(VENT), FIN)
        b1, b0 = p0, max(fc - dt.timedelta(VENT + 365), fechas[0])
        dp, db = (p1 - p0).days, (b1 - b0).days
        if dp < 30 or db < 90:
            continue
        rp, rb = sum(1 for f in fechas if p0 <= f <= p1) / (dp / 30.44), sum(1 for f in fechas if b0 <= f <= b1) / (db / 30.44)
        if rp or rb:
            pares.append(math.log((rp + .01) / (rb + .01)))
    arr = np.array(pares)
    boots = [math.exp(np.mean(rng.choice(arr, len(arr)))) for _ in range(2000)]
    d = {"window_days": VENT, "n_patients": len(arr), "geometric_ratio": round(math.exp(arr.mean()), 2), "boot95": "%.2f-%.2f" % (np.percentile(boots, 2.5), np.percentile(boots, 97.5))}
    ratios.append(d); print("  +/-%3d d: ratio %.2f (95%% CI %s), n=%d" % (VENT, d["geometric_ratio"], d["boot95"], len(arr)))
out["posting_rate_ratio_ci"] = ratios
vp = [r for r in csv.DictReader(open(os.path.join(SAL, "ventanas_por_paciente.csv"), encoding="utf-8-sig")) if r["discordant"] == "yes"]
post_days = [int(r["peri_days"]) - 90 for r in vp]
out["post_contact_exposure_days_discordant"] = {"median": st.median(post_days), "iqr": [sorted(post_days)[len(post_days) // 4], sorted(post_days)[3 * len(post_days) // 4]], "min": min(post_days), "n_truncated": sum(1 for r in vp if int(r["post_window_truncated_days"]) > 0)}
print("  post-contact observed exposure (18 patients): median %d d, IQR %s, min %d, truncated %d" % (out["post_contact_exposure_days_discordant"]["median"], out["post_contact_exposure_days_discordant"]["iqr"], min(post_days), out["post_contact_exposure_days_discordant"]["n_truncated"]))
# does the 57,300-follower patient remain in the 30?
out["outlier_patient_in_analysis"] = any(str(r.get("followers", "")).replace(",", "").replace("K", "000").startswith("57") for r in pac)

json.dump(out, open(os.path.join(SAL, "sensibilidad.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
with open(os.path.join(SAL, "sensibilidad_auc.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(tab[0].keys())); w.writeheader(); w.writerows(tab + sens)
print("\n-> resultados_ig/manuscrito/sensibilidad.json")
