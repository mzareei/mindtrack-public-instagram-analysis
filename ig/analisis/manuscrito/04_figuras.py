# -*- coding: utf-8 -*-
"""
Manuscript figures. Reads the outputs of 01-03 and the repository results.
Writes PNG (300 dpi) and PDF to resultados_ig/manuscrito/figuras/.

Figure 1  Study design and flow (patients, comparison group, three layers).
Figure 2  Between persons: cross-validated AUC of metadata, style and both,
          with bootstrap CIs and permutation nulls; univariate AUCs.
Figure 3  Within person: posting rate, style, and annotated categories,
          peri-episode vs baseline, per patient.
Figure 4  Self-reported social-media behaviour vs what is observable in
          public posts.
Figure S1 Agreement between the two language models per category.
"""
import csv, json, os, sys, math, statistics as st
import datetime as dt
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
RES = os.path.join(RAIZ, "resultados_ig")
M = os.path.join(RES, "manuscrito")
FIG = os.path.join(M, "figuras")
os.makedirs(FIG, exist_ok=True)
sys.path.insert(0, os.path.join(RAIZ, "ig", "analisis", "anotacion_llm"))
from anotar_llm import CODIGOS

# validated palette (dataviz reference instance, light mode)
BLUE, ORANGE, AQUA, GREY, INK, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#9a9891", "#0b0b0b", "#52514e"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#c9c8c2", "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
                     "grid.color": "#e8e7e2", "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False, "legend.fontsize": 8})
LABEL = {"expresion_simbolica": "Symbolic expression", "desesperanza": "Hopelessness", "carga_percibida": "Perceived burdensomeness",
         "pertenencia": "Thwarted belongingness", "dolor_psiquico": "Psychological pain", "atrapamiento": "Entrapment",
         "busqueda_de_apoyo": "Help-seeking", "despedida": "Farewell / closure"}
part = json.load(open(os.path.join(M, "participantes.json"), encoding="utf-8"))
corp = json.load(open(os.path.join(M, "corpus.json"), encoding="utf-8"))
inf = json.load(open(os.path.join(M, "inferencia.json"), encoding="utf-8"))


def save(fig, name):
    fig.savefig(os.path.join(FIG, name + ".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(os.path.join(FIG, name + ".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  ->", name)


# =============================================================================
# Figure 1: design and flow
# =============================================================================
import textwrap


def caja(ax, x, y_top, w, titulo, cuerpo, color="#f4f3ef", edge="#c9c8c2", fs=7.0, ancho=42):
    """Rounded box anchored at its top edge; height follows the text. Returns bottom y."""
    lines = []
    for par in cuerpo.split("\n"):
        lines += textwrap.wrap(par, ancho) or [""]
    lh = 0.20
    h = 0.34 + lh * len(lines) + 0.12
    ax.add_patch(FancyBboxPatch((x, y_top - h), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=color, ec=edge, lw=0.8))
    ax.text(x + w / 2, y_top - 0.12, titulo, ha="center", va="top", fontsize=fs + 0.6, fontweight="bold", color=INK)
    for i, l in enumerate(lines):
        ax.text(x + w / 2, y_top - 0.40 - lh * i - 0.02, l, ha="center", va="top", fontsize=fs, color=INK2)
    return y_top - h


def flecha(ax, x0, y0, x1, y1):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=9, lw=0.9, color=INK2))


fun = part["ig_funnel"]; cf = corp["control_funnel"]; ak = corp["annotation_kit"]; win = corp["windows"]
fig, ax = plt.subplots(figsize=(7.2, 6.9))
ax.set_xlim(0, 10); ax.set_ylim(1.1, 11.2); ax.axis("off")
GAP = 0.32
# left column: patients
ax.text(2.45, 11.05, "Patients (consented)", ha="center", fontsize=9.5, fontweight="bold", color=BLUE)
y = 10.75
pasos_p = [
    ("%d participants interviewed" % part["n_enrolled"], "Admitted for suicide risk to a psychiatric hospital in Zapopan, Mexico; aged 15-29; C-SSRS screened; interview on social-media use"),
    ("%d provided an Instagram handle" % part["ig_funnel_participants"]["Handles provided"], "%d handles: %d not found or invalid, %d private, %d public without posts (%d of the %d had completed the interview)" % (fun["Handles provided"], fun["Account not found / handle invalid"], fun["Private account"], fun["Public account without posts"], part["n_with_ig_handle"], part["ig_funnel_participants"]["Handles provided"])),
    ("%d public accounts with posts" % corp["corpus"][0]["accounts"], "%s posts, %s caption words; extraction 28 Aug 2026, coverage 99.8%% of declared posts" % (format(corp["corpus"][0]["posts"], ","), format(corp["corpus"][0]["words_total"], ","))),
    ("%d patients with posts in both windows" % win["discordant_patients"], "Peri-episode (+/-90 d around hospital contact): %d posts; baseline (365 d before): %d posts" % (win["peri_posts_total_discordant"], win["baseline_posts_total_discordant"])),
    ("%d posts in the blind annotation kit" % ak["posts"], "At most 20 per patient and window, sampled at random; %d peri-episode, %d baseline; opaque codes, no dates, shuffled" % (ak["peri"], ak["baseline"])),
]
for t, c in pasos_p:
    yb = caja(ax, 0.35, y, 4.2, t, c, color="#e6f0fb", edge=BLUE)
    if (t, c) != pasos_p[-1]:
        flecha(ax, 2.45, yb, 2.45, yb - GAP + 0.04)
    y = yb - GAP
# right column
ax.text(7.5, 11.05, "Comparison group (public Instagram)", ha="center", fontsize=9.5, fontweight="bold", color=ORANGE)
y = 10.75
pasos_c = [
    ("%s profiles triaged" % format(cf["triaged_profiles"], ","), "Seeded from school and university accounts of the same city; the patients' network (2,125 handles) and mental-health hashtags excluded a priori"),
    ("%d with verifiable age evidence" % cf["approved_with_age_evidence"], "Institutional tag %d, age in biography %d, age in own captions %d; no biometrics, no style-based inference" % (cf["evidence_type"]["institucion"], cf["evidence_type"]["bio"], cf["evidence_type"]["captions"])),
    ("%d profiles fully extracted" % cf["extracted_profiles_unified"], "%d public with posts and age evidence; %d removed on review (%d manual, %d by the non-person filter: organisations, brands, professionals, false age); %d eligible" % (cf["approved_extracted_public_with_posts"], cf["manually_discarded_after_review"], cf["removed_manual_review"], cf["removed_non_person_filter"], cf["eligible_pool"])),
    ("%d matched controls (2:1)" % cf["matched"], "Admission envelope derived from the patients; exact strata (age band x followers x activity), nearest neighbour on metadata propensity; %d from a neighbouring stratum" % cf["matched_from_neighbouring_stratum"]),
]
for t, c in pasos_c:
    yb = caja(ax, 5.45, y, 4.2, t, c, color="#fdece5", edge=ORANGE)
    if (t, c) != pasos_c[-1]:
        flecha(ax, 7.55, yb, 7.55, yb - GAP + 0.04)
    y = yb - GAP
# layers
ax.plot([0.35, 9.65], [3.8, 3.8], color="#c9c8c2", lw=0.8)
ax.text(0.35, 3.65, "Three layers, each a pre-specified gate for the next", fontsize=9, fontweight="bold", color=INK, va="top")
caja(ax, 0.35, 3.25, 2.95, "Layer 0: metadata", "14 account-shape features (followers, rhythm, posting hour, media mix). Between persons: sampling-frame audit. Within person: posting rate.", ancho=30)
caja(ax, 3.52, 3.25, 2.95, "Layer 1: writing style", "25 countable features (pronouns, absolutist words, emotion lexicons, emoji valence, timing, form). Between and within persons.", ancho=30)
caja(ax, 6.7, 3.25, 2.95, "Layer 2: content", "8 clinical categories from a codebook; two independent language-model raters, one post per call, blind. Within person, three versions.", ancho=30)
save(fig, "Figure1_design_flow")

# =============================================================================
# Figure 2: between persons
# =============================================================================
bp = inf["between_persons"]
sets = [("Metadata (14 features)", bp["metadata"]), ("Writing style (25 features)", bp["style"]), ("Metadata + style (39 features)", bp["metadata_plus_style"])]
uni_meta = inf["metadata_univariate"]
uni_style = list(csv.DictReader(open(os.path.join(RES, "capa1", "entre_personas.csv"), encoding="utf-8-sig")))

fig = plt.figure(figsize=(7.2, 6.8))
gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 2.6], hspace=0.5)
ax = fig.add_subplot(gs[0])
for i, (nombre, r) in enumerate(sets):
    y = 2 - i
    lo, hi = r["bootstrap95"]
    ax.plot([lo, hi], [y, y], color=BLUE, lw=2, solid_capstyle="round")
    ax.plot(r["auc_bagged"], y, "o", color=BLUE, ms=7, mec="white", mew=1)
    ax.plot([r["permutation"]["null_mean"] - 1.96 * r["permutation"]["null_sd"], r["permutation"]["null_mean"] + 1.96 * r["permutation"]["null_sd"]], [y - 0.28, y - 0.28], color=GREY, lw=5, alpha=0.35, solid_capstyle="butt")
    ax.text(hi + 0.012, y, "%.2f (%.2f to %.2f); permutation P=%.2f" % (r["auc_bagged"], lo, hi, r["permutation"]["p_two_sided"]), va="center", fontsize=7.8, color=INK2)
ax.axvline(0.5, color=INK2, lw=0.8, ls="--")
ax.axvspan(0.60, 1.0, color="#f4f3ef", zorder=0)
ax.text(0.605, 2.45, "pre-specified frame-bias gate (AUC > 0.60)", fontsize=7.2, color=INK2, va="center")
ax.set_yticks([2, 1, 0]); ax.set_yticklabels([s[0] for s in sets])
ax.set_xlim(0.2, 1.0); ax.set_ylim(-0.6, 2.7)
ax.set_xlabel("Cross-validated AUC, patients (n=30) vs matched controls (n=60)")
ax.set_title("A. Cross-validated separation of patients and matched controls")
ax.plot([], [], color=BLUE, lw=2, label="CV-bagged AUC with bootstrap 95% CI")
ax.plot([], [], color=GREY, lw=5, alpha=0.35, label="label-permutation null (mean +/- 1.96 SD)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.30), ncol=2, fontsize=7.2)

ax = fig.add_subplot(gs[1])
rows = [(r["feature"], float(r["auc"]), r["ci95"], "metadata") for r in uni_meta] + \
       [(r["rasgo"], float(r["auc"]), None, "style") for r in uni_style]
rows.sort(key=lambda t: t[1])
NICE = {"log_seguidores": "followers (log)", "log_siguiendo": "following (log)", "ratio_seg_sig": "followers/following", "log_n_posts": "posts (log)",
        "log_tasa_mes": "posts per month (log)", "antiguedad_anios": "account age (years)", "pct_video": "% video", "pct_carrusel": "% carousel",
        "hora_media": "mean posting hour", "dispersion_horas": "spread of posting hour", "pct_con_hashtag": "% with hashtag", "pct_con_ubicacion": "% with location",
        "long_media_caption": "caption length", "tiene_bio": "has biography",
        "p1s_100": "first-person singular /100 w", "p1p_100": "first-person plural /100 w", "p23_100": "2nd/3rd person /100 w", "absol_100": "absolutist words /100 w",
        "neg_100": "negations /100 w", "hedge_100": "hedges /100 w", "emo_neg_100": "negative-emotion words /100 w", "emo_pos_100": "positive-emotion words /100 w",
        "muerte_100": "death/pain words /100 w", "emoji_val": "emoji valence", "palabras_log": "words per post (log)", "emoji_pp": "emoji per word", "hashtag_pp": "hashtags per word",
        "mencion_pp": "mentions per word", "puntuacion": "emphatic punctuation", "noche_share": "share posted 00-06 h", "hora_circ": "circular mean hour", "finde_share": "share on weekends",
        "gap_mediana": "median gap between posts (d)", "burstiness": "burstiness of gaps", "video_share": "share video", "sin_cap_share": "share without caption",
        "solo_simb_share": "share caption only emoji/hashtags", "ingles_share": "share in English", "diversidad": "lexical diversity"}
for i, (f, a, ci, fam) in enumerate(rows):
    c = BLUE if fam == "metadata" else AQUA
    ax.plot([0.5, a], [i, i], color=c, lw=1.2, alpha=0.5)
    ax.plot(a, i, "o", color=c, ms=5, mec="white", mew=0.8)
ax.axvline(0.5, color=INK2, lw=0.8, ls="--")
ax.set_yticks(range(len(rows))); ax.set_yticklabels([NICE.get(f, f) for f, *_ in rows], fontsize=6.8)
ax.set_xlim(0.3, 0.7); ax.set_ylim(-1, len(rows))
ax.set_xlabel("Univariate AUC (>0.5 = higher in patients); none survives FDR correction")
ax.set_title("B. Feature by feature: metadata (blue) and writing style (green)")
ax.plot([], [], "o", color=BLUE, label="metadata"); ax.plot([], [], "o", color=AQUA, label="writing style")
ax.legend(loc="lower right", fontsize=7.2)
ax.grid(axis="x")
save(fig, "Figure3_between_persons")

# =============================================================================
# Figure 3: within person
# =============================================================================
ds = {r["ID"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "mindtrack_dataset_v1.csv"), encoding="utf-8-sig"))}
posts = defaultdict(list)
for p in csv.DictReader(open(os.path.join(RES, "extraccion", "posts.csv"), encoding="utf-8-sig")):
    if p["es_del_perfil"] == "si":
        posts[p["id"]].append(dt.date.fromisoformat(p["fecha"][:10]))
FIN = dt.date(2026, 8, 28)
pares = []
for pid, fechas in posts.items():
    row = ds.get(pid)
    if not row or not row["fecha_consentimiento"]:
        continue
    fc = dt.date.fromisoformat(row["fecha_consentimiento"]); fechas = sorted(fechas)
    p0, p1 = fc - dt.timedelta(90), min(fc + dt.timedelta(90), FIN)
    b1, b0 = p0, max(fc - dt.timedelta(455), fechas[0])
    dp, db = (p1 - p0).days, (b1 - b0).days
    if dp < 30 or db < 90:
        continue
    rp, rb = sum(1 for f in fechas if p0 <= f <= p1) / (dp / 30.44), sum(1 for f in fechas if b0 <= f <= b1) / (db / 30.44)
    if rp or rb:
        pares.append((pid, rp, rb))

clave = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RAIZ, "anotacion", "clave_anotacion.csv"), encoding="utf-8-sig"))}
cons = {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RES, "capa2", "etiquetas_consenso.csv"), encoding="utf-8-sig"))}
etq = {p: {r["codigo"]: r for r in csv.DictReader(open(os.path.join(RES, "capa2", "etiquetas_%s.csv" % p), encoding="utf-8-sig"))} for p in ("anthropic", "openai")}
NO_SIMB = [c for c in CODIGOS if c != "expresion_simbolica"]


def por_paciente(fn):
    d = defaultdict(lambda: {"peri": [], "base": []})
    for k, c in clave.items():
        v = fn(k)
        if v is not None:
            d[c["id_paciente"]][c["ventana"]].append(v)
    return {p: (st.mean(x["peri"]), st.mean(x["base"])) for p, x in d.items() if x["peri"] and x["base"]}


sim = por_paciente(lambda k: int(cons[k]["expresion_simbolica"]) if cons[k]["expresion_simbolica"] in ("0", "1") else None)


def any_marker(prov):
    def f(k):
        if prov == "consensus":
            vals = [cons[k][c] for c in NO_SIMB]
            if all(v not in ("0", "1") for v in vals):
                return None
            return 1 if "1" in vals else 0
        return 1 if any(etq[prov][k][c] == "1" for c in NO_SIMB) else 0
    return f


anym = {p: por_paciente(any_marker(p)) for p in ("consensus", "anthropic", "openai")}

fig = plt.figure(figsize=(7.2, 6.6))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.1], hspace=0.45, wspace=0.35)
ax = fig.add_subplot(gs[0, 0])
for pid, rp, rb in pares:
    c = BLUE if rp > rb else (ORANGE if rp < rb else GREY)
    ax.plot([0, 1], [rb + 0.01, rp + 0.01], "-o", color=c, ms=4, lw=1, alpha=0.85, mec="white", mew=0.5)
ax.set_yscale("log"); ax.set_xticks([0, 1]); ax.set_xticklabels(["Baseline\n(365 d before)", "Peri-episode\n(+/-90 d)"])
ax.set_ylabel("Posts per month (+0.01, log scale)")
up = sum(1 for _, rp, rb in pares if rp > rb); dn = sum(1 for _, rp, rb in pares if rp < rb)
ax.set_title("A. Posting rate, n=%d patients" % len(pares), pad=16)
ax.text(0, 1.01, "up in %d, down in %d; exact sign test P=1.00" % (up, dn), transform=ax.transAxes, ha="left", va="bottom", fontsize=7.5, color=INK2)
ax.set_xlim(-0.3, 1.3)

ax = fig.add_subplot(gs[0, 1])
rng = np.random.default_rng(3)
for i, (p, (a, b)) in enumerate(sim.items()):
    j = rng.uniform(-0.06, 0.06)
    c = BLUE if a > b else (ORANGE if a < b else GREY)
    ax.plot([0 + j, 1 + j], [b, a], "-o", color=c, ms=4, lw=1, alpha=0.85, mec="white", mew=0.5)
ax.set_xticks([0, 1]); ax.set_xticklabels(["Baseline", "Peri-episode"]); ax.set_xlim(-0.3, 1.3); ax.set_ylim(-0.03, 1.03)
ax.set_ylabel("Share of posts coded symbolic expression")
upS = sum(1 for a, b in sim.values() if a > b); dnS = sum(1 for a, b in sim.values() if a < b)
ax.set_title("B. Symbolic expression (consensus), n=%d" % len(sim), pad=16)
ax.text(0, 1.01, "up in %d, down in %d; sign P=1.00, Wilcoxon P=0.92" % (upS, dnS), transform=ax.transAxes, ha="left", va="bottom", fontsize=7.5, color=INK2)

ax = fig.add_subplot(gs[1, :])
ub = inf["peri_prevalence_bounds"]
cats = CODIGOS
xs = np.arange(len(cats))
for k, (ver, col, mk, off) in enumerate([("consensus", BLUE, "o", 0.0), ("anthropic", AQUA, "s", -0.22), ("openai", ORANGE, "D", 0.22)]):
    peri = [next(r for r in ub if r["category"] == c and r["version"] == ver)["peri_pct"] for c in cats]
    base = [next(r for r in ub if r["category"] == c and r["version"] == ver)["base_pct"] for c in cats]
    ax.scatter(xs + off - 0.07, base, marker=mk, s=26, facecolors="white", edgecolors=col, linewidths=1.2, zorder=3)
    ax.scatter(xs + off + 0.07, peri, marker=mk, s=26, color=col, zorder=3)
    for x, b_, p_ in zip(xs, base, peri):
        ax.plot([x + off - 0.07, x + off + 0.07], [b_, p_], color=col, lw=0.9, alpha=0.7)
import textwrap as _tw
SHORT = {"expresion_simbolica": "Symbolic\nexpression", "desesperanza": "Hopelessness", "carga_percibida": "Perceived\nburdensomeness", "pertenencia": "Thwarted\nbelongingness",
         "dolor_psiquico": "Psychological\npain", "atrapamiento": "Entrapment", "busqueda_de_apoyo": "Help-seeking", "despedida": "Farewell /\nclosure"}
ax.set_xticks(xs); ax.set_xticklabels([SHORT[c] for c in cats], fontsize=6.6)
ax.set_ylabel("% of annotated posts with the category")
ax.set_title("C. Eight categories: baseline (open markers) vs peri-episode (filled markers)")
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], marker="o", color=BLUE, ls="", label="consensus of both models"),
                   Line2D([], [], marker="s", color=AQUA, ls="", label="model A (claude-sonnet-4-5)"),
                   Line2D([], [], marker="D", color=ORANGE, ls="", label="model B (gpt-4o)")], loc="upper right", fontsize=7.2)
ax.grid(axis="y")
ax.set_ylim(-1, 40)
save(fig, "Figure4_within_person")

# =============================================================================
# Figure 4: self-report vs observable
# =============================================================================
sr = part["self_report"]
items = [("uses social media every day", "Uses social media every day"),
         ("use changes when feeling distressed", "Use changes when distressed"),
         ("uses social media when sad", "Turns to social media when sad"),
         ("posts public content", "Posts public content"),
         ("social media affects mood", "Social media affects mood"),
         ("has received support through social media", "Has received support online"),
         ("uses symbolic or indirect language to express mood", "Uses symbolic / indirect language for mood"),
         ("has sought help through social media", "Has sought help online"),
         ("shares feelings on social media", "Shares feelings on social media"),
         ("has had conversations about suicide on social media", "Has discussed suicide online")]
fig = plt.figure(figsize=(7.2, 4.6))
gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1], wspace=0.55)
ax = fig.add_subplot(gs[0])
vals = [sr[k]["all_interviewed_pct"] for k, _ in items][::-1]
labs = [l for _, l in items][::-1]
ax.barh(range(len(vals)), vals, color=BLUE, height=0.62)
for i, v in enumerate(vals):
    ax.text(v + 1.2, i, "%.0f%%" % v, va="center", fontsize=7.5, color=INK2)
ax.set_yticks(range(len(vals))); ax.set_yticklabels(labs, fontsize=7.8)
ax.set_xlim(0, 100); ax.set_xlabel("%% of participants (interview, n=%d)" % part["n_interviewed"])
ax.set_title("A. What patients report doing on social media")
ax.grid(axis="x")

ax = fig.add_subplot(gs[1])
c18 = anym["consensus"]
obs = [("Any distress category\nin >=1 baseline post", 100.0 * sum(1 for a, b in c18.values() if b > 0) / len(c18), ORANGE),
       ("Any distress category\nin >=1 peri-episode post", 100.0 * sum(1 for a, b in c18.values() if a > 0) / len(c18), BLUE),
       ("Symbolic expression\nin >=1 baseline post", 100.0 * sum(1 for a, b in sim.values() if b > 0) / len(sim), ORANGE),
       ("Symbolic expression\nin >=1 peri-episode post", 100.0 * sum(1 for a, b in sim.values() if a > 0) / len(sim), BLUE)][::-1]
ax.barh(range(len(obs)), [o[1] for o in obs], color=[o[2] for o in obs], height=0.62)
for i, o in enumerate(obs):
    ax.text(o[1] + 1.2, i, "%.0f%%" % o[1], va="center", fontsize=7.5, color=INK2)
ax.set_yticks(range(len(obs))); ax.set_yticklabels([o[0] for o in obs], fontsize=7.8)
ax.set_xlim(0, 100); ax.set_xlabel("%% of patients with annotated posts in both windows\n(consensus labels; n=%d distress, n=%d symbolic)" % (len(c18), len(sim)))
ax.set_title("B. What their public posts show")
ax.grid(axis="x")
save(fig, "Figure2_selfreport_vs_observed")

# =============================================================================
# Figure S1: agreement
# =============================================================================
agr = inf["agreement"]
fig, ax = plt.subplots(figsize=(7.2, 3.4))
xs = np.arange(len(agr))
ax.bar(xs - 0.2, [a["prev_A"] for a in agr], width=0.38, color=AQUA, label="Model A (claude-sonnet-4-5)")
ax.bar(xs + 0.2, [a["prev_B"] for a in agr], width=0.38, color=ORANGE, label="Model B (gpt-4o)")
ax.bar(xs, [a["both"] for a in agr], width=0.78, color="none", edgecolor=INK, lw=0.9, label="flagged by both")
for x, a in zip(xs, agr):
    ax.text(x, max(a["prev_A"], a["prev_B"]) + 1.5, "k=%.2f\nPABAK=%.2f" % (a["kappa"], a["pabak"]), ha="center", fontsize=6.8, color=INK2)
ax.set_xticks(xs); ax.set_xticklabels([SHORT[a["category"]] for a in agr], fontsize=6.6)
ax.set_ylabel("Posts flagged (of 212)"); ax.set_ylim(0, 80)
ax.set_title("Agreement between the two language models, per category")
ax.legend(loc="upper right", fontsize=7.2)
ax.grid(axis="y")
save(fig, "FigureS1_model_agreement")

# Figure S2: permutation nulls
fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.4), sharey=True)
for ax, (nombre, r) in zip(axes, sets):
    p = r["permutation"]
    x = np.linspace(0.2, 0.8, 200)
    ax.plot(x, np.exp(-0.5 * ((x - p["null_mean"]) / p["null_sd"]) ** 2), color=GREY, lw=1.5)
    ax.fill_between(x, 0, np.exp(-0.5 * ((x - p["null_mean"]) / p["null_sd"]) ** 2), color=GREY, alpha=0.15)
    ax.axvline(r["auc_cv_mean_20reps"], color=BLUE, lw=1.6)
    ax.set_title(nombre, fontsize=8)
    ax.set_xlabel("AUC under label permutation"); ax.set_yticks([])
    ax.text(0.98, 0.95, "observed %.3f\nnull %.3f +/- %.3f\nP=%.2f" % (r["auc_cv_mean_20reps"], p["null_mean"], p["null_sd"], p["p_two_sided"]), transform=ax.transAxes, ha="right", va="top", fontsize=7)
save(fig, "FigureS2_permutation_nulls")
print("done")
