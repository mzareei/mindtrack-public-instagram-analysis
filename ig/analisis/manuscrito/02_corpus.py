# -*- coding: utf-8 -*-
"""
Manuscript analysis 2: descriptives of the patient corpus, the matched control
corpus, the within-person windows and the blind annotation kit.

Inputs
  resultados_ig/global_20260828_163758.json                 patients (81 handles)
  resultados_ig/global_controles_unido_20260909_150153.json  controls (205 profiles)
  ig/control/controles_emparejados.csv                      the 60 matched controls
  ig/control/controles_evidencia.csv, candidatos_descartados.csv, triaje.csv  funnel
  mindtrack_dataset_v1.csv                                  consent dates
  anotacion/clave_anotacion.csv, corpus_anotacion.csv       annotation kit

Outputs (resultados_ig/manuscrito/)
  corpus_descriptivo.csv, corpus.json, ventanas_por_paciente.csv,
  embudo_controles.csv
"""
import csv, json, os, re, collections, statistics as st
import datetime as dt

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
RES = os.path.join(RAIZ, "resultados_ig")
SAL = os.path.join(RES, "manuscrito")
os.makedirs(SAL, exist_ok=True)
FIN_OBS = dt.date(2026, 8, 28)
VENT, BASE = 90, 365

import sys
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "estilo"))
from rasgos import _PALABRA, _HASHTAG, _MENCION, normalizar


def palabras(caption):
    """Alphabetic tokens outside hashtags and mentions: the same tokenizer as
    the style layer (rasgos.py), so word counts agree across the paper."""
    t = _MENCION.sub(" ", _HASHTAG.sub(" ", normalizar(caption)))
    return _PALABRA.findall(t)


def propios(r):
    return [p for p in (r.get("posts_data") or []) if p.get("es_del_perfil", True) in (True, "si", "True")]


def fecha(p):
    f = p.get("fecha_post_iso") or p.get("fecha")
    return dt.date.fromisoformat(str(f)[:10]) if f else None


def q(a, k):
    a = sorted(a)
    return a[int(k * (len(a) - 1))]


def describir(perfiles, etiqueta):
    posts = [p for r in perfiles for p in propios(r)]
    npp = [len(propios(r)) for r in perfiles]
    wl = [len(palabras(p.get("caption"))) for p in posts]
    con_texto = sum(1 for w in wl if w > 0)
    video = sum(1 for p in posts if p.get("video_url") or p.get("video_local"))
    fechas = [fecha(p) for p in posts if fecha(p)]
    seg = [float(str(r.get("followers") or "0").replace(",", "").replace("K", "e3").replace("M", "e6")) for r in perfiles]
    return {
        "group": etiqueta, "accounts": len(perfiles), "posts": len(posts),
        "posts_per_account_median": st.median(npp), "posts_per_account_iqr": "%d-%d" % (q(npp, .25), q(npp, .75)),
        "posts_per_account_min_max": "%d-%d" % (min(npp), max(npp)),
        "top4_share_of_posts_pct": round(100.0 * sum(sorted(npp, reverse=True)[:4]) / len(posts), 1),
        "words_total": sum(wl), "words_per_post_median": st.median(wl), "words_per_post_iqr": "%d-%d" % (q(wl, .25), q(wl, .75)),
        "posts_with_text_pct": round(100.0 * con_texto / len(posts), 1),
        "posts_without_text_pct": round(100.0 * (len(posts) - con_texto) / len(posts), 1),
        "posts_over_10_words_pct": round(100.0 * sum(1 for w in wl if w > 10) / len(posts), 1),
        "video_pct": round(100.0 * video / len(posts), 1),
        "accounts_with_no_words": sum(1 for r in perfiles if sum(len(palabras(p.get("caption"))) for p in propios(r)) == 0),
        "followers_median": st.median(seg), "followers_iqr": "%d-%d" % (q(seg, .25), q(seg, .75)),
        "first_post": min(fechas).isoformat(), "last_post": max(fechas).isoformat(),
        "posts_last_90d_before_extraction_pct": round(100.0 * sum(1 for f in fechas if (FIN_OBS - f).days <= 90) / len(fechas), 1),
        "posts_last_365d_before_extraction_pct": round(100.0 * sum(1 for f in fechas if (FIN_OBS - f).days <= 365) / len(fechas), 1),
    }


pac = [r for r in json.load(open(os.path.join(RES, "global_20260828_163758.json"), encoding="utf-8"))["resultados"]
       if r["estado_cuenta"] == "publica_con_posts"]
ctrl_all = json.load(open(os.path.join(RES, "global_controles_unido_20260909_150153.json"), encoding="utf-8"))["resultados"]
emp = list(csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "controles_emparejados.csv"), encoding="utf-8-sig")))
usados = {r["usuario"].lower() for r in emp}
ctrl = [r for r in ctrl_all if (r.get("usuario") or "").lower() in usados]
assert len(ctrl) == 60, len(ctrl)

filas = [describir(pac, "patients"), describir(ctrl, "matched controls")]
with open(os.path.join(SAL, "corpus_descriptivo.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
    w.writeheader()
    w.writerows(filas)
out = {"corpus": filas}

# ---- Within-person windows, per patient -------------------------------------
ds = {r["ID"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "mindtrack_dataset_v1.csv"), encoding="utf-8-sig"))}
vent = []
for r in sorted(pac, key=lambda r: r["id"]):
    fc = ds[r["id"]]["fecha_consentimiento"]
    if not fc:
        continue
    fc = dt.date.fromisoformat(fc)
    fechas = sorted(f for f in (fecha(p) for p in propios(r)) if f)
    p0, p1 = fc - dt.timedelta(VENT), min(fc + dt.timedelta(VENT), FIN_OBS)
    b0, b1 = max(fc - dt.timedelta(VENT + BASE), fechas[0]), p0
    n_peri = sum(1 for f in fechas if p0 <= f <= p1)
    n_pre = sum(1 for f in fechas if p0 <= f <= fc)
    n_post = sum(1 for f in fechas if fc < f <= p1)
    n_base = sum(1 for f in fechas if b0 <= f <= b1)
    vent.append({"id": r["id"], "age": ds[r["id"]]["edad"], "consent_date": fc.isoformat(), "n_posts_total": len(fechas),
                 "first_post": fechas[0].isoformat(), "last_post": fechas[-1].isoformat(),
                 "peri_days": (p1 - p0).days, "peri_posts": n_peri, "peri_pre_posts": n_pre, "peri_post_posts": n_post,
                 "baseline_days": (b1 - b0).days, "baseline_posts": n_base,
                 "discordant": "yes" if (n_peri and n_base) else "no",
                 "post_window_truncated_days": (fc + dt.timedelta(VENT) - FIN_OBS).days if fc + dt.timedelta(VENT) > FIN_OBS else 0})
with open(os.path.join(SAL, "ventanas_por_paciente.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(vent[0].keys()))
    w.writeheader()
    w.writerows(vent)
disc = [v for v in vent if v["discordant"] == "yes"]
out["windows"] = {
    "patients_with_consent_date": len(vent),
    "discordant_patients": len(disc),
    "patients_with_any_peri_post": sum(1 for v in vent if v["peri_posts"]),
    "patients_with_any_pre_episode_post_90d": sum(1 for v in vent if v["peri_pre_posts"]),
    "patients_with_any_baseline_post": sum(1 for v in vent if v["baseline_posts"]),
    "peri_posts_total_discordant": sum(v["peri_posts"] for v in disc),
    "baseline_posts_total_discordant": sum(v["baseline_posts"] for v in disc),
    "pre_episode_posts_discordant": sum(v["peri_pre_posts"] for v in disc),
    "post_episode_posts_discordant": sum(v["peri_post_posts"] for v in disc),
    "patients_with_truncated_post_window": sum(1 for v in disc if v["post_window_truncated_days"] > 0),
    "peri_posts_per_patient_median_discordant": st.median([v["peri_posts"] for v in disc]),
    "baseline_posts_per_patient_median_discordant": st.median([v["baseline_posts"] for v in disc]),
    "reasons_not_discordant": collections.Counter(
        ("no peri posts" if not v["peri_posts"] else "no baseline posts") for v in vent if v["discordant"] == "no"),
}

# ---- Annotation kit -----------------------------------------------------------
clave = list(csv.DictReader(open(os.path.join(RAIZ, "anotacion", "clave_anotacion.csv"), encoding="utf-8-sig")))
corpus = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "anotacion", "corpus_anotacion.csv"), encoding="utf-8-sig"))}
wl = [len(palabras(corpus[c["codigo"]]["texto"])) for c in clave]
out["annotation_kit"] = {
    "posts": len(clave), "patients": len({c["id_paciente"] for c in clave}),
    "peri": sum(1 for c in clave if c["ventana"] == "peri"), "baseline": sum(1 for c in clave if c["ventana"] != "peri"),
    "posts_with_text": sum(1 for w in wl if w > 0), "posts_without_text": sum(1 for w in wl if w == 0),
    "words_total": sum(wl), "words_median_with_text": st.median([w for w in wl if w > 0]),
    "posts_over_10_words": sum(1 for w in wl if w > 10), "posts_over_20_words": sum(1 for w in wl if w > 20),
    "video_posts": sum(1 for c in clave if "video" in (c["tipo_media"] or "")),
    "posts_per_patient_per_window_cap": 20,
    "per_patient_window_counts": collections.Counter((c["id_paciente"], c["ventana"]) for c in clave).most_common(5),
}

# ---- Control-group funnel -----------------------------------------------------
ev = list(csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "controles_evidencia.csv"), encoding="utf-8-sig")))
tri = list(csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "triaje.csv"), encoding="utf-8-sig")))
desc = list(csv.DictReader(open(os.path.join(RAIZ, "ig", "control", "candidatos_descartados.csv"), encoding="utf-8-sig")))
manual = {l.split("#")[0].strip().lower() for l in open(os.path.join(RAIZ, "ig", "control", "descartes_manuales.txt"), encoding="utf-8")
          if l.split("#")[0].strip()}
sys.path.insert(0, os.path.join(RAIZ, "ig", "control"))
from util import es_no_persona
ev_users = {r["usuario"].lower() for r in ev}
con_ev = [r for r in ctrl_all if (r.get("usuario") or "").lower() in ev_users and r["estado_cuenta"] == "publica_con_posts"]
rem_manual = [r for r in con_ev if (r.get("usuario") or "").lower() in manual]
resto = [r for r in con_ev if (r.get("usuario") or "").lower() not in manual]
rem_auto = [r for r in resto if es_no_persona(r.get("nombre"), r.get("biografia"), r.get("posts_data"), (r.get("usuario") or "").lower())]
vered = collections.Counter(r.get("veredicto") or r.get("etapa") or "" for r in tri)
out["control_funnel"] = {
    "triaged_profiles": len(tri), "triage_verdicts": dict(vered),
    "harvest_discarded_as_institutional_brand_or_impossible": len(desc),
    "approved_with_age_evidence": len(ev),
    "evidence_type": dict(collections.Counter(r["tipo_evidencia"] for r in ev)),
    "approved_extracted_public_with_posts": len(con_ev),
    "removed_manual_review": len(rem_manual),
    "removed_non_person_filter": len(rem_auto),
    "manually_discarded_after_review": len(rem_manual) + len(rem_auto),
    "eligible_pool": len(con_ev) - len(rem_manual) - len(rem_auto),
    "extracted_profiles_unified": len(ctrl_all),
    "extracted_public_with_posts": sum(1 for r in ctrl_all if r["estado_cuenta"] == "publica_con_posts"),
    "matched": len(emp),
    "matched_evidence_type": dict(collections.Counter(r["tipo_evidencia"] for r in emp)),
    "matched_from_neighbouring_stratum": sum(1 for r in emp if r["estrato_relajado"] == "si"),
    "matched_age_median": st.median([int(r["edad_inferida"]) for r in emp]),
}
with open(os.path.join(SAL, "embudo_controles.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["step", "n"])
    for k, v in out["control_funnel"].items():
        w.writerow([k, json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v])

json.dump(out, open(os.path.join(SAL, "corpus.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
