# MindTrack: public Instagram activity and suicidal crisis

Code, annotation codebook, rater prompt and derived non-identifying data for the article:

> Zareei M, Garcia-Ceja E, González Ramírez LP, Miaja Ávila M, Castellanos Macías YB, Sandoval Barajas M.
> *No detectable signal of suicidal crisis in the public Instagram activity of hospitalized young people in Mexico.*
> Manuscript submitted to *Scientific Reports* (2026).

MindTrack (project S.807) is funded by the Fundación Gonzalo Río Arronte, I.A.P., with co-investment from
Tecnologico de Monterrey.

## What the study did

We asked whether the public Instagram activity of 30 young people admitted to a psychiatric hospital in
Mexico for suicide risk carries a detectable trace of the crisis, at three levels:

| Level | What is measured | Between persons (vs 60 matched public accounts) | Within persons (±90 days vs preceding year) |
|---|---|---|---|
| 0 | Account metadata (14 features) | sampling-frame audit, L2 logistic regression, cross-validated AUC | posting rate, exact sign test |
| 1 | Writing style (25 countable features) | Mann-Whitney, univariate and multivariate AUC, FDR | sign and Wilcoxon tests, FDR |
| 2 | Clinically coded content (8 categories) | not applicable | two blind language-model raters, consensus, each rater, union |

All three levels were null.

## Repository layout

```
ig/scrappingData_ig.py            Instagram extraction pipeline (patients and comparison accounts)
ig/*.py                           extraction utilities (CSV export, anonymised regeneration, media repair)
ig/control/                       comparison-group construction: seeding, triage, age evidence,
                                  non-person filter, account-shape envelope, stratified matching,
                                  sampling-frame detector (detector_marco.py)
ig/analisis/ventanas_temporales.py  peri-episode and baseline windows
ig/analisis/estilo/               level 1: 25 style features and their tests; lexicos/ holds the word lists
ig/analisis/anotacion_llm/        level 2: two-rater language-model annotation, agreement, contrasts
ig/analisis/manuscrito/           every number, table and figure in the article (scripts 01 to 05)
anotacion/CODEBOOK.md             clinical annotation codebook
ig/analisis/anotacion_llm/prompt_codebook.md   rater prompt sent to both models
resultados_ig/                    derived, non-identifying outputs (see below)
```

## Derived data included

`resultados_ig/manuscrito/` holds the aggregate tables behind the article's tables and figures: Table 1
(`tabla1_participantes.csv`), self-reported items, selection analysis, Instagram and comparison-group funnels,
univariate metadata AUCs, sensitivity AUCs, window sensitivity, prevalence bounds, rater agreement with
confidence intervals, composite, pre-episode and union contrasts, the full inference and sensitivity results
(`*.json`), and Figures 1 to 4 and S1 to S2. `resultados_ig/capa1/` and `resultados_ig/capa2/` hold the
per-feature level 1 results and the per-category level 2 agreement and contrasts, plus the API cost of the
annotation run.

## Data not included, and why

The following cannot be shared under the terms of the ethics approval (Research Ethics Committee and Research
Committee, School of Medicine and Health Sciences, Tecnologico de Monterrey, folio
P000850-Mindtrack-CEIC-CR002):

- the clinical and interview dataset (`mindtrack_dataset_v1.csv`);
- raw posts, captions, images, comments and account identifiers of patients;
- handles, posts and per-account features of comparison accounts, whose holders did not consent;
- per-post annotation labels, per-patient windows and per-account cross-validation scores;
- the annotation key linking opaque codes to participants.

Personal handles that appeared in code comments as worked examples were replaced by placeholders, and study
identifiers in comments were masked. Seed accounts of public schools and universities in
`ig/control/cosechar_candidatos.py` are institutional accounts and are kept so the sampling frame is auditable.

Because the inputs above are withheld, the scripts document the analysis exactly but cannot be run end to end
from this repository alone. Researchers who want to verify a result can contact the corresponding author.

## Requirements

Python 3.11 or later. Estimators (logistic regression, AUC, Mann-Whitney, Wilcoxon, sign test, FDR) are written
in pure Python; NumPy and SciPy are used for resampling. Extraction uses Selenium. See `requirements.txt`.
Credentials go in a local `.env` file (template in `.env.example`); never commit it.

## Ethics

Patients gave written informed consent (assent plus parental consent for ages 15 to 17), covering the interview,
medical-record abstraction and retrospective extraction of their own public social media content. The
comparison group was treated as minimal-risk research on publicly accessible data: no interaction, no
re-contact, no re-identification, no biometric processing, pseudonymous codes, no analysis of their images,
nothing sent to external services, and aggregate reporting only. Browser automation is not permitted by
Instagram's terms of service; access was rate-limited under a single identified research account, and no raw
data are redistributed.

## License

Code is released under the Apache License 2.0 (`LICENSE`). Derived data tables and figures are released under
CC BY 4.0.

## Contact

Enrique Garcia-Ceja, Tecnologico de Monterrey, enrique.gc@tec.mx
