# -*- coding: utf-8 -*-
"""
Manuscript analysis 3: uncertainty, sensitivity and power for the null results.

Everything here re-uses the repository's own estimators (detector_marco.py,
rasgos.py, estadistica.py) and adds what a null result needs to be credible:

  A. Between persons (30 patients vs 60 matched controls)
     - a vectorised (numpy) re-implementation of detector_marco.entrenar that
       reproduces the pure-Python AUC to floating-point precision, so the
       resampling below is affordable;
     - CV-bagged account scores, bootstrap 95% CI of the AUC (2,000 stratified
       resamples of accounts) and DeLong 95% CI;
     - label-permutation test of the cross-validated AUC (1,000 permutations)
       for three feature sets: metadata (14), style (25), metadata + style (39).
  B. Within person (18 patients, peri-episode vs baseline)
     - minimum detectable effect of the exact sign test with n = 18 pairs;
     - composite "any distress marker" (union of the seven non-symbolic
       categories), three versions (consensus, model A, model B);
     - pre-episode-only window (the 90 days before consent) vs baseline;
     - rule-of-three upper bounds on peri-episode prevalence per category;
     - posting-rate sensitivity to the window (30, 60, 90, 180 days).
  C. Model-vs-model agreement
     - bootstrap 95% CI of Cohen's kappa and PABAK per category;
     - what the two models disagree about in `expresion_simbolica`.

Outputs: resultados_ig/manuscrito/inferencia.json and CSV tables.
"""
import csv, json, math, os, random, sys, statistics as st
import datetime as dt
from collections import Counter, defaultdict
import numpy as np
from scipy import stats

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
RES = os.path.join(RAIZ, "resultados_ig")
SAL = os.path.join(RES, "manuscrito")
os.makedirs(SAL, exist_ok=True)
sys.path.insert(0, os.path.join(RAIZ, "ig", "control"))
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "estilo"))
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "anotacion_llm"))
import detector_marco as dm
from rasgos import NOMBRES
from estadistica import wilcoxon_p, signo_p, bh_fdr
from entre_personas import imputar
from anotar_llm import CODIGOS

N_BOOT, N_PERM = 2000, 1000
out = {}


# =============================================================================
# A. Between persons
# =============================================================================
def entrenar_np(X, y, iters=3000, lr=0.1, l2=1.0):
    """Same algorithm as detector_marco.entrenar (full-batch gradient descent,
    same learning rate, same L2, same clipping), vectorised."""
    X = np.asarray(X, float); y = np.asarray(y, float)
    n, d = X.shape
    w = np.zeros(d); b = 0.0
    for _ in range(iters):
        z = np.clip(X @ w + b, -35, 35)
        e = 1.0 / (1.0 + np.exp(-z)) - y
        b -= lr * e.sum() / n
        w -= lr * (X.T @ e / n + l2 * w / n)
    return w, b


def predecir_np(X, w, b):
    z = np.clip(np.asarray(X, float) @ w + b, -35, 35)
    return 1.0 / (1.0 + np.exp(-z))


def estandarizar_np(X):
    X = np.asarray(X, float)
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def cv_scores(X, y, k=5, repeticiones=20, semilla=20260902):
    """Replicates detector_marco.cv_auc fold assignment exactly (same RNG,
    same stratified round-robin) and returns per-repetition AUCs plus the
    out-of-fold score of every account in every repetition."""
    rng = random.Random(semilla)
    X = np.asarray(X, float); y = list(y)
    n = len(y)
    aucs, S = [], np.full((repeticiones, n), np.nan)
    for r in range(repeticiones):
        idx1 = [i for i, v in enumerate(y) if v == 1]
        idx0 = [i for i, v in enumerate(y) if v == 0]
        rng.shuffle(idx1); rng.shuffle(idx0)
        pliegos = [[] for _ in range(k)]
        for grupo in (idx1, idx0):
            for m, i in enumerate(grupo):
                pliegos[m % k].append(i)
        for f in range(k):
            te = pliegos[f]
            tr = [i for i in range(n) if i not in set(te)]
            Xtr, mu, sd = estandarizar_np(X[tr])
            w, b = entrenar_np(Xtr, [y[i] for i in tr])
            S[r, te] = predecir_np((X[te] - mu) / sd, w, b)
        aucs.append(dm.auc([y[i] for i in range(n)], list(S[r])))
    return np.array(aucs), S


def auc_np(y, s):
    return dm.auc(list(y), list(s))


def delong_ci(y, s, alpha=0.05):
    """DeLong (1988) variance of the AUC via placement values."""
    y = np.asarray(y); s = np.asarray(s, float)
    pos, neg = s[y == 1], s[y == 0]
    m, n = len(pos), len(neg)
    v10 = np.array([(np.sum(p > neg) + 0.5 * np.sum(p == neg)) / n for p in pos])
    v01 = np.array([(np.sum(pos > q) + 0.5 * np.sum(pos == q)) / m for q in neg])
    a = v10.mean()
    var = v10.var(ddof=1) / m + v01.var(ddof=1) / n
    z = stats.norm.ppf(1 - alpha / 2)
    return a, max(0.0, a - z * math.sqrt(var)), min(1.0, a + z * math.sqrt(var))


def bootstrap_auc(y, s, n_boot=N_BOOT, semilla=1):
    rng = np.random.default_rng(semilla)
    y = np.asarray(y); s = np.asarray(s, float)
    i1, i0 = np.where(y == 1)[0], np.where(y == 0)[0]
    vals = []
    for _ in range(n_boot):
        b1 = rng.choice(i1, len(i1)); b0 = rng.choice(i0, len(i0))
        idx = np.concatenate([b1, b0])
        vals.append(auc_np(y[idx], s[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def permutacion(X, y, auc_obs, n_perm=N_PERM, semilla=20260910):
    rng = random.Random(semilla)
    ge, far = 0, 0
    nulos = []
    for i in range(n_perm):
        yp = list(y); rng.shuffle(yp)
        a, _ = cv_scores(X, yp, repeticiones=1, semilla=semilla + i)
        a = float(a[0]); nulos.append(a)
        ge += a >= auc_obs
        far += abs(a - 0.5) >= abs(auc_obs - 0.5)
    return {"p_one_sided_ge": (ge + 1) / (n_perm + 1), "p_two_sided": (far + 1) / (n_perm + 1),
            "null_mean": float(np.mean(nulos)), "null_sd": float(np.std(nulos)),
            "null_p95": float(np.percentile(nulos, 95))}


def analizar_conjunto(nombre, X, y, nombres):
    aucs, S = cv_scores(X, y, repeticiones=20)
    bag = np.nanmean(S, axis=0)               # CV-bagged score per account
    a_bag = auc_np(y, bag)
    lo_b, hi_b = bootstrap_auc(y, bag)
    a_d, lo_d, hi_d = delong_ci(y, bag)
    perm = permutacion(X, y, float(aucs.mean()))
    res = {"features": len(nombres), "n": len(y), "auc_cv_mean_20reps": float(aucs.mean()), "auc_cv_sd_20reps": float(aucs.std()),
           "auc_cv_first5_mean": float(aucs[:5].mean()), "auc_cv_first5_sd": float(aucs[:5].std()),
           "auc_bagged": a_bag, "bootstrap95": [lo_b, hi_b], "delong95": [lo_d, hi_d], "permutation": perm}
    print("  %-22s AUC(CV x20) %.3f (SD %.3f)  bagged %.3f  boot95 %.3f-%.3f  DeLong95 %.3f-%.3f  perm p(>=) %.3f, p(2s) %.3f, null 95th pct %.3f"
          % (nombre, res["auc_cv_mean_20reps"], res["auc_cv_sd_20reps"], a_bag, lo_b, hi_b, lo_d, hi_d,
             perm["p_one_sided_ge"], perm["p_two_sided"], perm["null_p95"]))
    return res, bag


print("A. BETWEEN PERSONS")
pac = dm.cargar_global(os.path.join(RES, "global_20260828_163758.json"))
ctrl_all = dm.cargar_global(os.path.join(RES, "global_controles_unido_20260909_150153.json"))
emp = list(csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "controles_emparejados.csv"), encoding="utf-8-sig")))
usados = {r["usuario"].lower() for r in emp}
ctrl = [r for r in ctrl_all if (r.get("usuario") or "").lower() in usados]
ctrl_id = {r["usuario"].lower(): r["id_control"] for r in emp}
ids = [r["id"] for r in pac] + [ctrl_id[r["usuario"].lower()] for r in ctrl]
X_meta = [dm.caracteristicas(r) for r in pac] + [dm.caracteristicas(r) for r in ctrl]
y = [1] * len(pac) + [0] * len(ctrl)

# equivalence check against the pure-Python implementation (5 repetitions, same seed)
a_py, sd_py, _, _ = dm.cv_auc(X_meta, y, k=5, repeticiones=5)
a_np, _ = cv_scores(X_meta, y, repeticiones=5)
print("  equivalence check: pure-Python AUC %.6f vs numpy %.6f (max |diff| %.2e)" % (a_py, a_np.mean(), abs(a_py - a_np.mean())))
out["equivalence_check"] = {"pure_python_auc": a_py, "numpy_auc": float(a_np.mean()), "abs_diff": abs(a_py - float(a_np.mean()))}

rc = {r["id"]: r for r in csv.DictReader(open(os.path.join(RES, "capa1", "rasgos_cuentas.csv"), encoding="utf-8-sig"))}
filas = []
for i in ids:
    r = rc[i]
    filas.append({n: (float(r[n]) if r[n] not in ("", "nan") else None) for n in NOMBRES})
X_style, imput = imputar(filas, NOMBRES)
X_both = [xm + xs for xm, xs in zip(X_meta, X_style)]

res_meta, bag_meta = analizar_conjunto("metadata (14)", X_meta, y, dm.NOMBRES_CARACT)
res_style, bag_style = analizar_conjunto("style (25)", X_style, y, NOMBRES)
res_both, bag_both = analizar_conjunto("metadata + style (39)", X_both, y, dm.NOMBRES_CARACT + NOMBRES)
out["between_persons"] = {"metadata": res_meta, "style": res_style, "metadata_plus_style": res_both}
with open(os.path.join(SAL, "puntuaciones_cv_cuentas.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["account", "group", "score_metadata", "score_style", "score_both"])
    for i, (a, g) in enumerate(zip(ids, y)):
        w.writerow([a if g == 1 else "CTRL", "patient" if g else "control", round(bag_meta[i], 4), round(bag_style[i], 4), round(bag_both[i], 4)])

# univariate metadata features with CI
uni = []
for j, n in enumerate(dm.NOMBRES_CARACT):
    col = [x[j] for x in X_meta]
    a, lo, hi = delong_ci(y, col)
    p = stats.mannwhitneyu([c for c, yy in zip(col, y) if yy], [c for c, yy in zip(col, y) if not yy], alternative="two-sided").pvalue
    uni.append({"feature": n, "auc": round(a, 3), "ci95": "%.3f-%.3f" % (lo, hi), "p_mannwhitney": round(p, 3)})
qs = bh_fdr([u["p_mannwhitney"] for u in uni])
for u, q_ in zip(uni, qs):
    u["q_fdr"] = round(q_, 3)
uni.sort(key=lambda u: -abs(u["auc"] - 0.5))
with open(os.path.join(SAL, "metadatos_univariados.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(uni[0].keys())); w.writeheader(); w.writerows(uni)
out["metadata_univariate"] = uni

# =============================================================================
# B. Within person
# =============================================================================
print("\nB. WITHIN PERSON")
clave = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "anotacion", "clave_anotacion.csv"), encoding="utf-8-sig"))}
ds = {r["ID"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "mindtrack_dataset_v1.csv"), encoding="utf-8-sig"))}
etq = {p: {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RES, "capa2", "etiquetas_%s.csv" % p), encoding="utf-8-sig"))}
       for p in ("anthropic", "openai")}
cons = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RES, "capa2", "etiquetas_consenso.csv"), encoding="utf-8-sig"))}
NO_SIMB = [c for c in CODIGOS if c != "expresion_simbolica"]


def mde_signo(n, alpha=0.05):
    """Smallest k (out of n non-tied pairs) that is significant two-sided."""
    for k in range(n, n // 2, -1):
        if signo_p(k, n - k) < alpha:
            continue
        return k + 1
    return n


out["sign_test_mde"] = {n: {"k_needed": mde_signo(n), "share_of_patients": round(mde_signo(n) / n, 2)} for n in (10, 13, 15, 16, 18)}
print("  sign test, n=18: need %d of 18 in one direction (p<0.05 two-sided)" % mde_signo(18))


def contraste(valor_fn, nombre, ventana_peri=lambda c: c["ventana"] == "peri", solo_pre=False):
    """valor_fn(codigo) -> 0/1/None. Aggregates to patient x window."""
    por = defaultdict(lambda: {"peri": [], "base": []})
    for k, c in clave.items():
        v = valor_fn(k)
        if v is None:
            continue
        if c["ventana"] == "peri":
            if solo_pre:
                fc = dt.date.fromisoformat(ds[c["id_paciente"]]["fecha_consentimiento"])
                if dt.date.fromisoformat(c["fecha"]) > fc:
                    continue
            por[c["id_paciente"]]["peri"].append(v)
        else:
            por[c["id_paciente"]]["base"].append(v)
    pares = [(p, d) for p, d in por.items() if d["peri"] and d["base"]]
    difs = [st.mean(d["peri"]) - st.mean(d["base"]) for _, d in pares]
    sube, baja = sum(1 for x in difs if x > 0), sum(1 for x in difs if x < 0)
    peri_k, peri_n = sum(sum(d["peri"]) for _, d in pares), sum(len(d["peri"]) for _, d in pares)
    base_k, base_n = sum(sum(d["base"]) for _, d in pares), sum(len(d["base"]) for _, d in pares)
    pac_peri = sum(1 for _, d in pares if sum(d["peri"]))
    pac_base = sum(1 for _, d in pares if sum(d["base"]))
    return {"version": nombre, "n_patients": len(pares), "up": sube, "down": baja, "tie": len(pares) - sube - baja,
            "peri": "%d/%d" % (peri_k, peri_n), "baseline": "%d/%d" % (base_k, base_n),
            "peri_pct": round(100.0 * peri_k / peri_n, 1) if peri_n else None, "base_pct": round(100.0 * base_k / base_n, 1) if base_n else None,
            "patients_with_marker_peri": pac_peri, "patients_with_marker_baseline": pac_base,
            "p_sign": signo_p(sube, baja), "p_wilcoxon": wilcoxon_p(difs),
            "peri_upper95_rule_of_three_pct": round(100.0 * 3.0 / peri_n, 1) if peri_n and peri_k == 0 else None,
            "peri_upper95_exact_pct": round(100.0 * stats.beta.ppf(0.975, peri_k + 1, peri_n - peri_k), 1) if peri_n else None}


def v_cons(cat):
    return lambda k: (int(cons[k][cat]) if cons[k][cat] in ("0", "1") else None)


def v_model(p, cat):
    return lambda k: int(etq[p][k][cat])


def v_any(fn_by_cat):
    def f(k):
        vals = [fn_by_cat(c)(k) for c in NO_SIMB]
        if all(v is None for v in vals):
            return None
        return 1 if any(v == 1 for v in vals) else 0
    return f


comp = []
for nombre, fn in [("consensus", v_cons), ("anthropic", lambda c: v_model("anthropic", c)), ("openai", lambda c: v_model("openai", c))]:
    r = contraste(v_any(fn), nombre); r["category"] = "any of 7 distress categories"; comp.append(r)
    r = contraste(v_any(fn), nombre + " (pre-episode only)", solo_pre=True); r["category"] = "any of 7 distress categories"; comp.append(r)
    for cat in CODIGOS:
        r = contraste(fn(cat), nombre + " (pre-episode only)", solo_pre=True); r["category"] = cat; comp.append(r)
with open(os.path.join(SAL, "contraste_compuesto_y_preepisodio.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["category"] + [k for k in comp[0].keys() if k != "category"]); w.writeheader(); w.writerows(comp)
out["composite_and_pre_episode"] = comp
for r in comp:
    if r["category"].startswith("any"):
        print("  %-38s %-28s n=%d up %d down %d  peri %s  base %s  p_sign %.3f  p_wilc %s  patients w/ marker peri %d base %d" % (
            r["version"], r["category"], r["n_patients"], r["up"], r["down"], r["peri"], r["baseline"], r["p_sign"],
            ("%.3f" % r["p_wilcoxon"]) if r["p_wilcoxon"] == r["p_wilcoxon"] else "nan", r["patients_with_marker_peri"], r["patients_with_marker_baseline"]))

# upper bounds on peri prevalence per category (consensus + each model)
ub = []
for cat in CODIGOS:
    for nombre, fn in [("consensus", v_cons), ("anthropic", lambda c: v_model("anthropic", c)), ("openai", lambda c: v_model("openai", c))]:
        r = contraste(fn(cat), nombre)
        ub.append({"category": cat, "version": nombre, "peri": r["peri"], "peri_pct": r["peri_pct"],
                   "peri_upper95_exact_pct": r["peri_upper95_exact_pct"], "baseline": r["baseline"], "base_pct": r["base_pct"],
                   "patients_with_marker_peri": r["patients_with_marker_peri"], "patients_with_marker_baseline": r["patients_with_marker_baseline"]})
with open(os.path.join(SAL, "prevalencia_peri_cotas.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(ub[0].keys())); w.writeheader(); w.writerows(ub)
out["peri_prevalence_bounds"] = ub

# posting-rate sensitivity to window length
print("  posting rate, window sensitivity:")
posts = defaultdict(list)
for p in csv.DictReader(open(os.path.join(RES, "extraccion", "posts.csv"), encoding="utf-8-sig")):
    if p["es_del_perfil"] == "si":
        posts[p["id"]].append(dt.date.fromisoformat(p["fecha"][:10]))
FIN = dt.date(2026, 8, 28)
vol = []
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
            pares.append((rp, rb))
    sube = sum(1 for rp, rb in pares if rp > rb); baja = sum(1 for rp, rb in pares if rp < rb)
    geo = math.exp(st.mean([math.log((rp + .01) / (rb + .01)) for rp, rb in pares]))
    d = {"window_days": VENT, "n_patients": len(pares), "up": sube, "down": baja, "p_sign": signo_p(sube, baja),
         "p_wilcoxon": wilcoxon_p([rp - rb for rp, rb in pares]), "geometric_ratio_peri_over_base": round(geo, 2)}
    vol.append(d)
    print("    +/-%3d d: n=%d up %d down %d p_sign %.3f p_wilc %.3f ratio %.2f" % (VENT, len(pares), sube, baja, d["p_sign"], d["p_wilcoxon"], geo))
with open(os.path.join(SAL, "volumen_sensibilidad_ventana.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(vol[0].keys())); w.writeheader(); w.writerows(vol)
out["posting_rate_window_sensitivity"] = vol

# =============================================================================
# C. Agreement between the two models
# =============================================================================
print("\nC. AGREEMENT")


def kappa(a, b):
    a, b = np.asarray(a), np.asarray(b)
    po = np.mean(a == b)
    pe = np.mean(a) * np.mean(b) + (1 - np.mean(a)) * (1 - np.mean(b))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan"), 2 * po - 1


codes = sorted(clave)
agr = []
rng = np.random.default_rng(7)
for cat in CODIGOS:
    a = np.array([int(etq["anthropic"][k][cat]) for k in codes]); b = np.array([int(etq["openai"][k][cat]) for k in codes])
    k0, pab0 = kappa(a, b)
    ks, ps = [], []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(codes), len(codes))
        kk, pp = kappa(a[idx], b[idx]); ks.append(kk); ps.append(pp)
    ks = [x for x in ks if x == x]
    agr.append({"category": cat, "prev_A": int(a.sum()), "prev_B": int(b.sum()), "both": int((a & b).sum()),
                "only_A": int((a & ~b).sum()), "only_B": int((~a & b).sum()), "agreement": round(float(np.mean(a == b)), 3),
                "kappa": round(k0, 3), "kappa_ci95": "%.2f to %.2f" % (np.percentile(ks, 2.5), np.percentile(ks, 97.5)),
                "pabak": round(pab0, 3), "pabak_ci95": "%.2f to %.2f" % (np.percentile(ps, 2.5), np.percentile(ps, 97.5))})
    print("  %-20s A %2d B %2d both %2d  agree %.3f  kappa %.2f (%s)  PABAK %.2f" % (cat, a.sum(), b.sum(), (a & b).sum(), np.mean(a == b), k0, agr[-1]["kappa_ci95"], pab0))
with open(os.path.join(SAL, "acuerdo_modelos_ic.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(agr[0].keys())); w.writeheader(); w.writerows(agr)
out["agreement"] = agr

# temporal orientation and confidence
ot = [(etq["anthropic"][k]["orientacion_temporal"], etq["openai"][k]["orientacion_temporal"]) for k in codes]
out["temporal_orientation"] = {"agreement": round(float(np.mean([x == y_ for x, y_ in ot])), 3),
                               "A_dist": dict(Counter(x for x, _ in ot)), "B_dist": dict(Counter(y_ for _, y_ in ot))}
out["confidence"] = {p: dict(Counter(etq[p][k]["confianza"] for k in codes)) for p in etq}

# what the models disagree about in expresion_simbolica
corpus = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "anotacion", "corpus_anotacion.csv"), encoding="utf-8-sig"))}
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "estilo"))
from rasgos import _EMOJI, _PALABRA, _HASHTAG, _MENCION


def perfil(ks):
    n = len(ks)
    if not n:
        return {}
    txt = [corpus[k]["texto"] or "" for k in ks]
    return {"n": n,
            "no_text_pct": round(100.0 * sum(1 for t in txt if not t.strip()) / n),
            "no_words_pct": round(100.0 * sum(1 for t in txt if not _PALABRA.findall(_MENCION.sub(" ", _HASHTAG.sub(" ", t)))) / n),
            "emoji_pct": round(100.0 * sum(1 for t in txt if _EMOJI.search(t)) / n),
            "video_pct": round(100.0 * sum(1 for k in ks if "video" in (clave[k]["tipo_media"] or "")) / n),
            "words_median": st.median([len(_PALABRA.findall(_MENCION.sub(" ", _HASHTAG.sub(" ", t)))) for t in txt]),
            "A_confidence_high_pct": round(100.0 * sum(1 for k in ks if etq["anthropic"][k]["confianza"] == "alta") / n)}


cat = "expresion_simbolica"
both = [k for k in codes if etq["anthropic"][k][cat] == "1" and etq["openai"][k][cat] == "1"]
onlyA = [k for k in codes if etq["anthropic"][k][cat] == "1" and etq["openai"][k][cat] == "0"]
onlyB = [k for k in codes if etq["anthropic"][k][cat] == "0" and etq["openai"][k][cat] == "1"]
neither = [k for k in codes if etq["anthropic"][k][cat] == "0" and etq["openai"][k][cat] == "0"]
out["symbolic_disagreement_profile"] = {"both": perfil(both), "only_anthropic": perfil(onlyA), "only_openai": perfil(onlyB), "neither": perfil(neither)}
print("  expresion_simbolica profiles:", json.dumps(out["symbolic_disagreement_profile"]))

# API cost
out["api_cost"] = json.load(open(os.path.join(RES, "capa2", "costo_api.json"), encoding="utf-8"))

json.dump(out, open(os.path.join(SAL, "inferencia.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
print("\n-> resultados_ig/manuscrito/inferencia.json")
