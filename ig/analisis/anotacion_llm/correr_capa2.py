# -*- coding: utf-8 -*-
"""
CAPA 2 en una orden, DESPUES de que anotar_llm.py haya etiquetado.

    python ig/analisis/anotacion_llm/correr_capa2.py

Que hace:
  1. Acuerdo entre los dos modelos (kappa por categoria), cola de
     adjudicacion humana, muestra de validez, etiquetas de consenso.
  2. Contraste intrasujeto sobre las categorias: consenso (principal) y cada
     modelo por separado (sensibilidad).
  3. REPORTE_capa2.md con todo, legible.

Se puede correr tantas veces como se quiera: cuando una persona rellene
`decision_humana_*` en desacuerdos.csv, volver a correr y el consenso las
incorpora.

Salidas en resultados_ig/capa2/:
  etiquetas_<proveedor>.csv/.jsonl    lo que devolvio cada modelo
  acuerdo.csv                         kappa por categoria
  desacuerdos.csv                     LA COLA HUMANA: rellenar decision_humana_*
  muestra_validez.csv                 20% de coincidencias para comprobar a mano
  etiquetas_consenso.csv              entrada del contraste
  contraste_capa2.csv                 el contraste, tres versiones
  REPORTE_capa2.md                    el resumen
"""

import csv, os, sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
SAL = os.path.join(RAIZ, "resultados_ig", "capa2")
sys.path.insert(0, DIR)
import acuerdo
import contraste_capa2 as cc
from anotar_llm import CODIGOS, PROVEEDORES

_LOG = []


def log(m=""):
    print(m, flush=True)
    _LOG.append(m)


def main():
    inicio = datetime.now()
    log("CAPA 2: CATEGORIAS ANOTADAS POR DOS MODELOS   %s" % inicio.strftime("%Y-%m-%d %H:%M"))
    log("=" * 72)
    faltantes = [p for p in PROVEEDORES if not os.path.exists(os.path.join(SAL, "etiquetas_%s.csv" % p))]
    if faltantes:
        sys.exit("Faltan etiquetas de: %s. Corre antes anotar_llm.py" % ", ".join(faltantes))
    modelos = {}
    for p in PROVEEDORES:
        with open(os.path.join(SAL, "etiquetas_%s.csv" % p), encoding="utf-8-sig") as f:
            r = next(csv.DictReader(f), None)
            modelos[p] = r["modelo"] if r else "?"
    log("  modelos: " + ", ".join("%s=%s" % kv for kv in modelos.items()))
    simulado = any(m == "SIMULADO" for m in modelos.values())
    if simulado:
        log("  ATENCION: etiquetas SIMULADAS. Esto es una prueba del pipeline, no un resultado.")

    res_ac = acuerdo.correr(log=log)
    res_ct, n_adj, faltan = cc.correr(log=log)

    # ---- reporte ----
    L = []
    L.append("# Capa 2: categorías anotadas por dos modelos de lenguaje")
    L.append("")
    if simulado:
        L.append("> **ETIQUETAS SIMULADAS.** Este reporte prueba el pipeline con etiquetas al azar. No es un resultado.")
        L.append("")
    L.append("Generado por `ig/analisis/anotacion_llm/correr_capa2.py` el %s. Modelos: %s."
             % (inicio.strftime("%Y-%m-%d %H:%M"), ", ".join("%s (%s)" % (p, m) for p, m in modelos.items())))
    L.append("")
    L.append("## Acuerdo entre los dos modelos")
    L.append("")
    L.append("%d publicaciones. Coinciden en todo en %d; %d tienen algún desacuerdo (%d decisiones humanas pendientes). Orientación temporal: %.0f%% de acuerdo bruto."
             % (res_ac["n"], res_ac["coinciden"], res_ac["desacuerdos"], res_ac["decisiones"], 100 * res_ac["ot_acuerdo"]))
    L.append("")
    L.append("| categoría | prev. A | prev. B | acuerdo | κ Cohen | PABAK | lectura | usable |")
    L.append("|---|---|---|---|---|---|---|---|")
    for t in res_ac["tabla"]:
        L.append("| %s | %s | %s | %.0f%% | %s | %.3f | %s | %s |" % (t["categoria"], t["prevalencia_A"], t["prevalencia_B"],
                 100 * t["acuerdo_bruto"], t["kappa"] if t["kappa"] != "" else "n/a", t["pabak"], t["calificacion"], t["usable"]))
    L.append("")
    L.append("κ < 0.60 no se tira: se reporta y se excluye del contraste principal o se fusiona. Con categorías raras, PABAK es la cifra justa; κ de Cohen castiga la prevalencia baja.")
    L.append("")
    L.append("## Contraste intrasujeto")
    L.append("")
    L.append("Unidad: proporción de posts del paciente en cada ventana que llevan la categoría. Diferencia = peri − basal. Signo exacto, Wilcoxon pareado, FDR sobre 8.")
    L.append("")
    for r in res_ct:
        L.append("### %s (%d pacientes)" % (r["nombre"], r["n_pacientes"]))
        L.append("")
        L.append("| categoría | n | sube | baja | peri | basal | p signo | p Wilcoxon | q |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for f in r["filas"]:
            m = " **" if (f["q_fdr"] == f["q_fdr"] and f["q_fdr"] < 0.05) else ""
            L.append("| %s%s | %d | %d | %d | %s (%.0f%%) | %s (%.0f%%) | %.3f | %.3f | %.3f |" % (
                f["categoria"], m, f["n_pacientes"], f["sube"], f["baja"], f["posts_peri"], f["pct_peri"],
                f["posts_base"], f["pct_base"], f["p_signo"], f["p_wilcoxon"], f["q_fdr"]))
        L.append("")
    if n_adj:
        L.append("Celdas adjudicadas a mano incorporadas al consenso: %d." % n_adj)
    if faltan:
        L.append("Celdas de consenso aún vacías (desacuerdos sin adjudicar): %d. El contraste de consenso las ignora; adjudicar y volver a correr." % faltan)
    L.append("")
    L.append("## Cómo leer esto")
    L.append("")
    L.append("- La conclusión vale si sale igual en las tres versiones (consenso, modelo A, modelo B). Si cambia según el modelo, no es una conclusión.")
    L.append("- Con ~18 pacientes y 8 categorías, solo efectos grandes sobreviven FDR. \"Sube en 13 de 18\" informa más que el p.")
    L.append("- El acuerdo entre modelos NO es validez: dos modelos pueden coincidir en el mismo error. Por eso existe `muestra_validez.csv`: una persona comprueba el 20% de las coincidencias.")
    L.append("- Sesgo conocido de los modelos: sobredetectan malestar en texto ambiguo. Si las prevalencias salen altas, mirar la muestra de validez antes de creerlas.")
    L.append("")
    L.append("## Qué hace falta de una persona")
    L.append("")
    L.append("1. `desacuerdos.csv`: rellenar `decision_humana_<categoría>` (0 o 1) en las celdas listadas. %d decisiones." % res_ac["decisiones"])
    L.append("2. `muestra_validez.csv`: rellenar `humano_<categoría>` para los %d posts. Sirve para calcular κ humano-vs-modelos." % res_ac["validez"])
    L.append("3. Volver a correr `correr_capa2.py`.")
    with open(os.path.join(SAL, "REPORTE_capa2.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(SAL, "salida_consola_capa2.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(_LOG) + "\n")
    log("\n  -> resultados_ig/capa2/REPORTE_capa2.md")
    log("  duracion: %s" % str(datetime.now() - inicio).split(".")[0])


if __name__ == "__main__":
    main()
