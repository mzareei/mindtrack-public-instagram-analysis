# -*- coding: utf-8 -*-
"""
Manuscript analysis 1: participants, self-reported social-media behaviour and
selection into the analysable Instagram sample.

Inputs
  mindtrack_dataset_v1.csv           clinical + interview dataset (107 IDs)
  resultados_ig/global_20260828_163758.json   Instagram extraction (81 handles)

Outputs (resultados_ig/manuscrito/)
  tabla1_participantes.csv     Table 1: all enrolled / with IG handle / analysable
  tabla_autoinforme_redes.csv  interview items on social-media behaviour
  seleccion_30_vs_resto.csv    analysable (30) vs rest: age, gender, risk, attempt
  embudo_instagram.csv         account-status funnel
  participantes.json           every number, for the text

Python 3 standard library + scipy (for Fisher / Mann-Whitney only).
"""
import csv, json, os, sys, collections, statistics as st
from scipy import stats

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
SAL = os.path.join(RAIZ, "resultados_ig", "manuscrito")
os.makedirs(SAL, exist_ok=True)

ds = list(csv.DictReader(open(os.path.join(RAIZ, "mindtrack_dataset_v1.csv"), encoding="utf-8-sig")))
g = json.load(open(os.path.join(RAIZ, "resultados_ig", "global_20260828_163758.json"), encoding="utf-8"))["resultados"]
estado = {r["id"]: r["estado_cuenta"] for r in g}
publicos = {r["id"] for r in g if r["estado_cuenta"] == "publica_con_posts"}

# Analysis population: participants with a clinical record and interview.
enrolled = [r for r in ds if r["en_entrevista"] == "1"]
con_ig = [r for r in enrolled if r["ID"] in estado]
analizables = [r for r in enrolled if r["ID"] in publicos]
grupos = [("All interviewed participants", enrolled),
          ("Instagram handle provided", con_ig),
          ("Public Instagram account with posts (analysable)", analizables)]

out = {"n_dataset_ids": len(ds), "n_enrolled": len(enrolled), "n_with_ig_handle": len(con_ig),
       "n_analysable": len(analizables)}


def pct(k, n):
    """k/N (%) with the denominator of participants who have the variable recorded."""
    return "%d/%d (%.0f%%)" % (k, n, 100.0 * k / n) if n else "0"


def edad_de(r):
    return int(r["edad"]) if r["edad"].isdigit() else None


def dx_grupo(code):
    c = (code or "").strip().upper().replace(" ", "")
    if not c:
        return "Missing/pending"
    if c.startswith("F32") or c.startswith("F33") or c.startswith("F34"):
        return "Depressive disorders (F32-F34)"
    if c.startswith("F1"):
        return "Substance use disorders (F10-F19)"
    if c.startswith("F6"):
        return "Personality disorders (F60-F69)"
    return "Other"


def n_int(v):
    v = (v or "").strip()
    if v.isdigit():
        return int(v)
    if "20" in v:
        return 20
    if "5-10" in v:
        return 7
    return None


filas = []


def fila(nombre, f):
    row = {"variable": nombre}
    for etiqueta, grp in grupos:
        row[etiqueta] = f(grp)
    filas.append(row)


def cont(campo, valor):
    return lambda grp: pct(sum(1 for r in grp if r[campo] == valor), sum(1 for r in grp if r[campo]))


fila("N", lambda grp: str(len(grp)))
fila("Age, median (IQR)", lambda grp: (lambda a: "%d (%d-%d)" % (st.median(a), sorted(a)[len(a) // 4], sorted(a)[3 * len(a) // 4]))([edad_de(r) for r in grp if edad_de(r)]))
fila("Age 15-17", lambda grp: pct(sum(1 for r in grp if edad_de(r) and edad_de(r) <= 17), sum(1 for r in grp if edad_de(r))))
fila("Age 18-21", lambda grp: pct(sum(1 for r in grp if edad_de(r) and 18 <= edad_de(r) <= 21), sum(1 for r in grp if edad_de(r))))
fila("Age 22-25", lambda grp: pct(sum(1 for r in grp if edad_de(r) and 22 <= edad_de(r) <= 25), sum(1 for r in grp if edad_de(r))))
fila("Age 26-29", lambda grp: pct(sum(1 for r in grp if edad_de(r) and edad_de(r) >= 26), sum(1 for r in grp if edad_de(r))))
fila("Gender: women", lambda grp: pct(sum(1 for r in grp if r["genero"] == "Femenino"), sum(1 for r in grp if r["genero"])))
fila("Gender: men", lambda grp: pct(sum(1 for r in grp if r["genero"] in ("Masculino", "Hombre")), sum(1 for r in grp if r["genero"])))
fila("Gender: non-binary", lambda grp: pct(sum(1 for r in grp if r["genero"] == "No binario"), sum(1 for r in grp if r["genero"])))
fila("Occupation: student", cont("ocupacion", "Estudiante"))
fila("Education: secondary or less", lambda grp: pct(sum(1 for r in grp if r["escolaridad"] in ("Primaria", "Secundaria")), sum(1 for r in grp if r["escolaridad"])))
fila("Education: upper secondary (preparatoria)", cont("escolaridad", "Preparatoria"))
fila("Education: university or postgraduate", lambda grp: pct(sum(1 for r in grp if r["escolaridad"] in ("Licenciatura", "Posgrado")), sum(1 for r in grp if r["escolaridad"])))
fila("Admission diagnosis: depressive disorders (F32-F34)", lambda grp: pct(sum(1 for r in grp if dx_grupo(r["dx_ingreso_cie10"]) == "Depressive disorders (F32-F34)"), len(grp)))
fila("Admission diagnosis: missing or pending", lambda grp: pct(sum(1 for r in grp if dx_grupo(r["dx_ingreso_cie10"]) == "Missing/pending"), len(grp)))
fila("Risk at admission rated high", cont("riesgo_ingreso", "Alto"))


def cssrs_screener(r):
    """C-SSRS screener risk from the six recorded items, standard triage rules:
    high = intent (4) or plan (5) or suicidal behaviour (6) in the past 3 months;
    moderate = method (3) or lifetime behaviour; low = wish to be dead (1) or thoughts (2)."""
    y = lambda c: r[c] == "Si"
    if not any(r[c] for c in ("c1_deseo_muerte", "c2_ideacion", "c6_conducta")):
        return None
    if y("c4_intencion") or y("c5_plan") or (y("c6_conducta") and y("c6_ultimos3meses")):
        return "high"
    if y("c3_metodo") or y("c6_conducta"):
        return "moderate"
    if y("c1_deseo_muerte") or y("c2_ideacion"):
        return "low"
    return "negative"


fila("C-SSRS screener risk category: high", lambda grp: pct(sum(1 for r in grp if cssrs_screener(r) == "high"),
                                                           sum(1 for r in grp if cssrs_screener(r))))
fila("Voluntary admission", cont("ingreso_voluntario", "Si"))
fila("Previous suicide attempt", cont("intento_previo", "Si"))
fila("Number of previous attempts, median (IQR)", lambda grp: (lambda a: "%d (%d-%d)" % (st.median(a), sorted(a)[len(a) // 4], sorted(a)[3 * len(a) // 4]) if a else "-")([n_int(r["num_intentos_raw"]) for r in grp if n_int(r["num_intentos_raw"])]))
fila("Family history of suicidal behaviour", cont("antecedente_familiar_riesgo", "Si"))
fila("Substance use diagnosis", cont("dx_sustancias", "Si"))
fila("C-SSRS: suicidal ideation (item 2)", cont("c2_ideacion", "Si"))
fila("C-SSRS: plan (item 5)", cont("c5_plan", "Si"))
fila("C-SSRS: suicidal behaviour (item 6)", cont("c6_conducta", "Si"))
fila("C-SSRS: suicidal behaviour in last 3 months", cont("c6_ultimos3meses", "Si"))
fila("Social insurance: IMSS", cont("seguridad_social", "IMSS"))

with open(os.path.join(SAL, "tabla1_participantes.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["variable"] + [e for e, _ in grupos])
    w.writeheader()
    w.writerows(filas)

# ---- Self-reported social-media behaviour (interview) --------------------------
items = [
    ("uses social media every day", "frecuencia_uso", "Todos los días"),
    ("Instagram is the favourite platform", "red_favorita", "Instagram"),
    ("TikTok is the favourite platform", "red_favorita", "TikTok"),
    ("posts public content", "contenido_publico", "Si"),
    ("use changes when feeling distressed", "cambia_uso_malestar", "Si"),
    ("uses social media when sad", "usa_rs_triste", "Si"),
    ("uses social media when anxious", "usa_rs_ansioso", "Si"),
    ("shares feelings on social media", "comparte_sentimientos", "Si"),
    ("uses symbolic or indirect language to express mood", "lenguaje_simbolico", "Si"),
    ("has had conversations about suicide on social media", "conversaciones_suicidio", "Si"),
    ("knows online groups related to suicide or self-harm", "conoce_grupos", "Si"),
    ("has sought help through social media", "busco_ayuda_rs", "Si"),
    ("has received support through social media", "recibio_apoyo_rs", "Si"),
    ("has shared personal experiences online", "compartio_experiencias", "Si"),
    ("social media affects mood", "impacto_animo", "Si"),
    ("feels a constant need to be connected", "necesidad_constante", "Si"),
]
entrevistados = [r for r in enrolled if r["en_entrevista"] == "1"]
analiz_entrev = [r for r in analizables if r["en_entrevista"] == "1"]
auto = []
for etiqueta, campo, valor in items:
    n_all = sum(1 for r in entrevistados if r[campo])
    k_all = sum(1 for r in entrevistados if r[campo] == valor)
    n_30 = sum(1 for r in analiz_entrev if r[campo])
    k_30 = sum(1 for r in analiz_entrev if r[campo] == valor)
    auto.append({"item": etiqueta, "all_interviewed_n": n_all, "all_interviewed_k": k_all,
                 "all_interviewed_pct": round(100.0 * k_all / n_all, 1) if n_all else None,
                 "analysable_n": n_30, "analysable_k": k_30,
                 "analysable_pct": round(100.0 * k_30 / n_30, 1) if n_30 else None})
horas = []
for r in entrevistados:
    try:
        horas.append(float(r["horas_rs_dia"].replace("hrs", "").replace("-", " ").split()[0]))
    except (ValueError, IndexError):
        pass
out["self_report"] = {a["item"]: a for a in auto}
out["hours_per_day_median"] = st.median(horas) if horas else None
out["hours_per_day_iqr"] = [sorted(horas)[len(horas) // 4], sorted(horas)[3 * len(horas) // 4]] if horas else None
out["n_interviewed"] = len(entrevistados)
out["n_analysable_interviewed"] = len(analiz_entrev)
with open(os.path.join(SAL, "tabla_autoinforme_redes.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(auto[0].keys()))
    w.writeheader()
    w.writerows(auto)

# ---- Instagram funnel ---------------------------------------------------------
# Funnel per HANDLE (one participant gave two handles, both non-existent), with the
# number of distinct participants alongside.
cnt = collections.Counter(r["estado_cuenta"] for r in g)
embudo = [{"status": "Handles provided", "n": len(g), "participants": len(estado)},
          {"status": "Account not found / handle invalid", "n": cnt.get("no_existe", 0), "participants": len({r["id"] for r in g if r["estado_cuenta"] == "no_existe"})},
          {"status": "Private account", "n": cnt.get("privada", 0), "participants": len({r["id"] for r in g if r["estado_cuenta"] == "privada"})},
          {"status": "Public account without posts", "n": cnt.get("publica_sin_posts", 0), "participants": len({r["id"] for r in g if r["estado_cuenta"] == "publica_sin_posts"})},
          {"status": "Public account with posts (analysable)", "n": cnt.get("publica_con_posts", 0), "participants": len(publicos)}]
out["ig_funnel"] = {e["status"]: e["n"] for e in embudo}
out["ig_funnel_participants"] = {e["status"]: e["participants"] for e in embudo}
out["handle_providers_interviewed"] = len(con_ig)
with open(os.path.join(SAL, "embudo_instagram.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["status", "n", "participants"])
    w.writeheader()
    w.writerows(embudo)

# ---- Selection: analysable 30 vs the rest of enrolled --------------------------
resto = [r for r in enrolled if r["ID"] not in publicos]
sel = []
a_age = [edad_de(r) for r in analizables if edad_de(r)]
b_age = [edad_de(r) for r in resto if edad_de(r)]
u = stats.mannwhitneyu(a_age, b_age, alternative="two-sided")
sel.append({"variable": "Age (median)", "analysable": st.median(a_age), "rest": st.median(b_age),
            "test": "Mann-Whitney U", "p": round(u.pvalue, 3)})
for etiqueta, campo, valor in [("Women", "genero", "Femenino"), ("Student", "ocupacion", "Estudiante"),
                                ("Previous attempt", "intento_previo", "Si"), ("High risk at admission", "riesgo_ingreso", "Alto")] + \
                               [("Self-report: " + e, c, v) for e, c, v in items]:
    a1 = sum(1 for r in analizables if r[campo] == valor); a0 = sum(1 for r in analizables if r[campo] and r[campo] != valor)
    b1 = sum(1 for r in resto if r[campo] == valor); b0 = sum(1 for r in resto if r[campo] and r[campo] != valor)
    p = stats.fisher_exact([[a1, a0], [b1, b0]])[1]
    sel.append({"variable": etiqueta, "analysable": "%d/%d (%.0f%%)" % (a1, a1 + a0, 100.0 * a1 / (a1 + a0)),
                "rest": "%d/%d (%.0f%%)" % (b1, b1 + b0, 100.0 * b1 / (b1 + b0)), "test": "Fisher exact", "p": round(p, 3)})
with open(os.path.join(SAL, "seleccion_30_vs_resto.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["variable", "analysable", "rest", "test", "p"])
    w.writeheader()
    w.writerows(sel)
out["selection"] = sel

# Consent dates (index episode) of the analysable sample
fechas = sorted(r["fecha_consentimiento"] for r in analizables if r["fecha_consentimiento"])
out["consent_dates_analysable"] = {"min": fechas[0], "max": fechas[-1]}
fechas_all = sorted(r["fecha_consentimiento"] for r in enrolled if r["fecha_consentimiento"] and r["fecha_consentimiento"] >= "2025")
out["consent_dates_enrolled_excluding_2021_outlier"] = {"min": fechas_all[0], "max": fechas_all[-1]}
out["red_favorita_all"] = dict(collections.Counter(r["red_favorita"] for r in entrevistados if r["red_favorita"]))
out["tiene_instagram_registered"] = sum(1 for r in enrolled if r["tiene_instagram"] == "1")

json.dump(out, open(os.path.join(SAL, "participantes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("PARTICIPANTS")
for row in filas:
    print("  %-50s %-14s %-14s %-14s" % (row["variable"][:50], *[row[e][:14] for e, _ in grupos]))
print("\nSELF-REPORT (n=%d interviewed; n=%d analysable interviewed)" % (len(entrevistados), len(analiz_entrev)))
for a in auto:
    print("  %-55s %5.1f%% (%d/%d)   analysable %5.1f%% (%d/%d)" % (a["item"], a["all_interviewed_pct"], a["all_interviewed_k"], a["all_interviewed_n"], a["analysable_pct"] or 0, a["analysable_k"], a["analysable_n"]))
print("  hours/day median %.1f IQR %s" % (out["hours_per_day_median"], out["hours_per_day_iqr"]))
print("\nFUNNEL", out["ig_funnel"])
print("\nSELECTION")
for s in sel:
    print("  %-40s %-16s %-16s p=%s" % (s["variable"], s["analysable"], s["rest"], s["p"]))
print("\nconsent dates analysable:", out["consent_dates_analysable"])
