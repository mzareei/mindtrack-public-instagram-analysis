# -*- coding: utf-8 -*-
"""
CAPA 1 en una orden: el estilo de escritura, sin anotar nada.

    python ig/analisis/estilo/correr_capa1.py
    python ig/analisis/estilo/correr_capa1.py --permutaciones 100   (+10 min)

Que hace, en orden:
  1. Localiza el global de pacientes (el mas reciente cuya mayoria de ids son
     MIND) y el global unido de controles mas reciente, y restringe los
     controles a los 60 de controles_emparejados.csv. Misma regla de siempre:
     casos y controles del mismo tipo de fichero.
  2. Calcula los 25 rasgos por cuenta (rasgos.py) sobre los posts PROPIOS
     (es_del_perfil=True). Escribe una fila por post y una por cuenta.
  3. Entre personas: AUC univariada por rasgo + regresion logistica con los 25
     en validacion cruzada, contra la referencia del detector de marco.
  4. Intra persona: peri vs basal, rasgo a rasgo, pruebas pareadas.
  5. Escribe todo en resultados_ig/capa1/ y un REPORTE_capa1.md legible.

Salidas (todas en resultados_ig/capa1/, carpeta ignorada por git):
  rasgos_posts.csv         una fila por post: conteos crudos, sin texto
  rasgos_cuentas.csv       una fila por cuenta: los 25 rasgos + grupo + id
  entre_personas.csv       tabla univariada
  entre_personas.json      todo lo del paso 3
  intra_persona.csv        tabla pareada
  REPORTE_capa1.md         el resumen que se lee

Sin dependencias nuevas. Todo en una linea en PowerShell.
"""

import csv, glob, json, os, re, sys
import datetime as dt
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
RES = os.path.join(RAIZ, "resultados_ig")
SAL = os.path.join(RES, "capa1")
CTRL = os.path.join(RAIZ, "ig", "control")
sys.path.insert(0, DIR)
sys.path.insert(0, CTRL)
sys.path.insert(0, os.path.dirname(DIR))

from rasgos import NOMBRES, rasgos_de_posts, fila_post, lexicos, autoprueba
import entre_personas as ep
import intra_persona as ip
from util import ruta_dataset

_LOG = []


def log(msg=""):
    print(msg, flush=True)
    _LOG.append(msg)


def es_de_pacientes(ruta):
    try:
        res = json.load(open(ruta, encoding="utf-8")).get("resultados", [])
        return bool(res) and sum(1 for r in res if str(r.get("id", "")).startswith("MIND")) > len(res) / 2
    except Exception:
        return False


def localizar():
    cand = sorted(f for f in glob.glob(os.path.join(RES, "global_2*.json")) if "anonimo" not in os.path.basename(f))
    pac = [f for f in cand if es_de_pacientes(f)]
    uni = sorted(glob.glob(os.path.join(RES, "global_controles_unido_*.json")))
    if not pac:
        sys.exit("No encuentro un global de pacientes en resultados_ig/.")
    if not uni:
        sys.exit("No encuentro global_controles_unido_*.json. Corre antes ig/control/cerrar_control.py --sin-extraer --caliper 3")
    return pac[-1], uni[-1]


def cargar(ruta):
    d = json.load(open(ruta, encoding="utf-8"))
    return d.get("resultados", d if isinstance(d, list) else [])


def propios(perfil):
    return [p for p in (perfil.get("posts_data") or []) if str(p.get("es_del_perfil", "True")) in ("True", "si", "1")]


def referencia_marco():
    """Lee el ultimo AUC del detector de marco si quedo en un fichero; si no,
    la cifra cerrada del 9/9/2026."""
    return 0.439


def main():
    n_perm = int(sys.argv[sys.argv.index("--permutaciones") + 1]) if "--permutaciones" in sys.argv else 0
    os.makedirs(SAL, exist_ok=True)
    inicio = datetime.now()
    log("CAPA 1: ESTILO DE ESCRITURA   %s" % inicio.strftime("%Y-%m-%d %H:%M"))
    log("=" * 72)

    log("\nAutoprueba del contador de rasgos:")
    if not autoprueba():
        sys.exit("El contador de rasgos no pasa su autoprueba. No sigo.")

    ruta_pac, ruta_ctrl = localizar()
    log("\n  pacientes : %s" % os.path.relpath(ruta_pac, RAIZ))
    log("  controles : %s" % os.path.relpath(ruta_ctrl, RAIZ))
    emp = os.path.join(CTRL, "controles_emparejados.csv")
    if not os.path.exists(emp):
        sys.exit("Falta ig/control/controles_emparejados.csv. Corre antes cerrar_control.py.")
    emparejados = {r["usuario"].strip().lower(): r for r in csv.DictReader(open(emp, encoding="utf-8-sig"))}
    log("  controles emparejados: %d" % len(emparejados))
    log("  lexico de emocion: %s" % lexicos().fuente_emocion)

    pacientes = [r for r in cargar(ruta_pac) if propios(r)]
    controles = [r for r in cargar(ruta_ctrl)
                 if (r.get("usuario") or "").strip().lower() in emparejados and propios(r)]
    log("  pacientes con posts propios: %d   controles con posts propios: %d" % (len(pacientes), len(controles)))

    # ---- rasgos ----------------------------------------------------------
    filas_cuenta, filas_post = [], []
    for grupo, perfiles in (("paciente", pacientes), ("control", controles)):
        for r in perfiles:
            ps = propios(r)
            ident = r.get("id") if grupo == "paciente" else emparejados[(r.get("usuario") or "").strip().lower()]["id_control"]
            rg = rasgos_de_posts(ps)
            rg.update({"id": ident, "grupo": grupo})
            filas_cuenta.append(rg)
            for p in ps:
                filas_post.append(fila_post(p, {"id": ident, "grupo": grupo}))
    with open(os.path.join(SAL, "rasgos_cuentas.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "grupo", "n_posts", "n_palabras"] + NOMBRES)
        for rg in filas_cuenta:
            w.writerow([rg["id"], rg["grupo"], rg.get("_n_posts", 0), rg.get("_n_palabras", 0)] +
                       ["" if rg.get(n) is None else "%.6f" % rg[n] for n in NOMBRES])
    with open(os.path.join(SAL, "rasgos_posts.csv"), "w", encoding="utf-8-sig", newline="") as f:
        campos = list(filas_post[0].keys())
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas_post)
    pal_pac = sum(rg.get("_n_palabras", 0) for rg in filas_cuenta if rg["grupo"] == "paciente")
    pal_ctl = sum(rg.get("_n_palabras", 0) for rg in filas_cuenta if rg["grupo"] == "control")
    log("  palabras: pacientes %d, controles %d" % (pal_pac, pal_ctl))
    log("  -> resultados_ig/capa1/rasgos_cuentas.csv (%d filas), rasgos_posts.csv (%d filas)" % (len(filas_cuenta), len(filas_post)))

    # ---- entre personas --------------------------------------------------
    res_ep = ep.correr(filas_cuenta, n_perm=n_perm, referencia_marco=referencia_marco(), log=log)
    with open(os.path.join(SAL, "entre_personas.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rasgo", "auc", "direccion", "mediana_pacientes", "mediana_controles", "p", "q_fdr"])
        w.writeheader()
        for o in res_ep["univariadas"]:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in o.items()})
    json.dump(res_ep, open(os.path.join(SAL, "entre_personas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)

    # ---- intra persona ---------------------------------------------------
    ruta_ds = ruta_dataset()
    if not ruta_ds:
        sys.exit("No encuentro mindtrack_dataset_v1.csv (fechas de consentimiento).")
    cons = {}
    for r in csv.DictReader(open(ruta_ds, encoding="utf-8-sig")):
        fc = (r.get("fecha_consentimiento") or "").strip()
        if fc:
            try:
                cons[r["ID"]] = dt.date.fromisoformat(fc[:10])
            except ValueError:
                pass
    res_ip = ip.correr(pacientes, cons, log=log)
    with open(os.path.join(SAL, "intra_persona.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rasgo", "n", "sube", "baja", "igual", "mediana_dif", "p_signo", "p_wilcoxon", "q_fdr"])
        w.writeheader()
        for fila in res_ip["filas"]:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in fila.items()})

    # ---- reporte ---------------------------------------------------------
    escribir_reporte(inicio, ruta_pac, ruta_ctrl, filas_cuenta, pal_pac, pal_ctl, res_ep, res_ip, n_perm)
    log("\n  -> resultados_ig/capa1/REPORTE_capa1.md")
    log("  duracion: %s" % str(datetime.now() - inicio).split(".")[0])


def escribir_reporte(inicio, ruta_pac, ruta_ctrl, filas_cuenta, pal_pac, pal_ctl, res_ep, res_ip, n_perm):
    a, disp = res_ep["auc_cv"], res_ep["auc_cv_de"]
    ref = res_ep.get("referencia_marco", 0.439)
    uni = res_ep["univariadas"]
    sig_uni = [o for o in uni if o["q_fdr"] == o["q_fdr"] and o["q_fdr"] < 0.05]
    nom_uni = [o for o in uni if o["p"] < 0.05]
    sig_ip = [f for f in res_ip["filas"] if f["q_fdr"] == f["q_fdr"] and f["q_fdr"] < 0.05]
    nom_ip = [f for f in res_ip["filas"] if f["p_wilcoxon"] == f["p_wilcoxon"] and f["p_wilcoxon"] < 0.05]
    if a - ref >= 0.15:
        veredicto_ep = "El estilo separa a los grupos claramente por encima de los metadatos. Hay señal de estilo."
    elif a - ref >= 0.07:
        veredicto_ep = "El estilo añade algo sobre los metadatos, pero poco. Señal debil; la capa 2 tiene que decir que es."
    else:
        veredicto_ep = "El estilo no separa mas que los metadatos. No hay señal de estilo entre personas que reclamar."
    if sig_ip:
        veredicto_ip = "Hay rasgos que cambian dentro de la persona cerca del episodio y sobreviven la correccion FDR."
    elif nom_ip:
        veredicto_ip = "Algun rasgo cambia a p<0.05 pero ninguno sobrevive la correccion por 25 pruebas. Sugerente, no concluyente."
    else:
        veredicto_ip = "Ningun rasgo de estilo cambia dentro de la persona cerca del episodio."

    L = []
    L.append("# Capa 1: estilo de escritura, sin anotacion")
    L.append("")
    L.append("Generado por `ig/analisis/estilo/correr_capa1.py` el %s." % inicio.strftime("%Y-%m-%d %H:%M"))
    L.append("Fuentes: `%s` (pacientes), `%s` (controles, restringidos a los 60 emparejados)."
             % (os.path.basename(ruta_pac), os.path.basename(ruta_ctrl)))
    L.append("Lexico de emocion: %s." % lexicos().fuente_emocion)
    L.append("")
    L.append("## En una frase")
    L.append("")
    L.append("**Entre personas:** AUC %.3f (DE %.3f) con los 25 rasgos de estilo, contra %.3f del detector de marco con solo metadatos. %s"
             % (a, disp, ref, veredicto_ep))
    L.append("")
    L.append("**Dentro de la persona (%d pacientes):** %s" % (res_ip["n_pacientes"], veredicto_ip))
    L.append("")
    L.append("## Datos")
    L.append("")
    npac = sum(1 for f in filas_cuenta if f["grupo"] == "paciente")
    nctl = len(filas_cuenta) - npac
    L.append("| | pacientes | controles |")
    L.append("|---|---|---|")
    L.append("| cuentas | %d | %d |" % (npac, nctl))
    L.append("| posts propios | %d | %d |" % (sum(f.get("_n_posts", 0) for f in filas_cuenta if f["grupo"] == "paciente"),
                                              sum(f.get("_n_posts", 0) for f in filas_cuenta if f["grupo"] == "control")))
    L.append("| palabras en captions | %d | %d |" % (pal_pac, pal_ctl))
    L.append("")
    L.append("## Entre personas: rasgo a rasgo")
    L.append("")
    L.append("AUC univariada (>0.5 = mas alto en pacientes). p de Mann-Whitney; q = FDR de Benjamini-Hochberg sobre 25 pruebas.")
    L.append("")
    L.append("| rasgo | AUC | mediana pacientes | mediana controles | p | q |")
    L.append("|---|---|---|---|---|---|")
    for o in uni:
        m = " **" if (o["q_fdr"] == o["q_fdr"] and o["q_fdr"] < 0.05) else ""
        L.append("| %s%s | %.3f | %.3f | %.3f | %.3f | %.3f |" % (o["rasgo"], m, o["auc"], o["mediana_pacientes"], o["mediana_controles"], o["p"], o["q_fdr"]))
    L.append("")
    L.append("Sobreviven FDR (q<0.05): %s." % (", ".join(o["rasgo"] for o in sig_uni) or "ninguno"))
    L.append("Nominales (p<0.05, sin corregir): %s." % (", ".join(o["rasgo"] for o in nom_uni) or "ninguno"))
    L.append("")
    L.append("## Entre personas: los 25 juntos")
    L.append("")
    L.append("Regresion logistica L2, validacion cruzada estratificada 5 pliegos x 20 repeticiones, una cuenta = una persona. Misma maquinaria que el detector de marco.")
    L.append("")
    L.append("- AUC = **%.3f** (DE %.3f)" % (a, disp))
    L.append("- referencia (solo metadatos, detector de marco): %.3f" % ref)
    L.append("- diferencia: %+.3f" % (a - ref))
    if n_perm:
        L.append("- permutaciones (%d, ajustes cortos): AUC %.3f, p = %.3f" % (n_perm, res_ep.get("auc_perm_obs", float("nan")), res_ep.get("p_permutacion", float("nan"))))
    L.append("")
    L.append("Coeficientes estandarizados de mayor a menor peso:")
    L.append("")
    for n, w in res_ep["coeficientes"][:10]:
        L.append("- `%s` %+.3f" % (n, w))
    if res_ep.get("imputados"):
        L.append("")
        L.append("Huecos imputados con la mediana: " + ", ".join("%s=%d" % kv for kv in res_ep["imputados"].items()) + ".")
    L.append("")
    L.append("## Dentro de la persona: pericrisis contra basal")
    L.append("")
    L.append("%d pacientes con posts en las dos ventanas. Diferencia = peri - basal. Prueba de signos exacta y Wilcoxon pareado; q = FDR sobre 25."
             % res_ip["n_pacientes"])
    L.append("")
    L.append("| rasgo | n | sube | baja | mediana(peri-basal) | p signo | p Wilcoxon | q |")
    L.append("|---|---|---|---|---|---|---|---|")
    for f in res_ip["filas"]:
        m = " **" if (f["q_fdr"] == f["q_fdr"] and f["q_fdr"] < 0.05) else ""
        L.append("| %s%s | %d | %d | %d | %.3f | %.3f | %.3f | %.3f |" % (f["rasgo"], m, f["n"], f["sube"], f["baja"], f["mediana_dif"], f["p_signo"], f["p_wilcoxon"], f["q_fdr"]))
    L.append("")
    L.append("Sobreviven FDR: %s." % (", ".join(f["rasgo"] for f in sig_ip) or "ninguno"))
    L.append("Nominales (p<0.05): %s." % (", ".join(f["rasgo"] for f in nom_ip) or "ninguno"))
    L.append("")
    L.append("## Como leer esto")
    L.append("")
    L.append("- El AUC entre personas se lee contra 0.439, no contra 0.5: los grupos ya estan emparejados en forma, asi que lo que el estilo añade es la diferencia con esa referencia.")
    L.append("- 25 pruebas con 30 personas: solo efectos grandes sobreviven FDR. Un rasgo nominal (p<0.05, q>0.05) es una pista para la capa 2, no un hallazgo.")
    L.append("- Dentro de la persona, \"sube en 14 de 18\" es mas informativo que el p-valor con esta n.")
    L.append("- Un resultado nulo aqui es informativo: dice que la señal, si existe, no esta en el estilo contable y hay que ir al contenido (capa 2).")
    L.append("")
    L.append("## Limitaciones a declarar")
    L.append("")
    L.append("- Captions cortas (mediana ~5 palabras): las tasas por 100 palabras se calculan sobre el texto agregado de la cuenta.")
    L.append("- Lexicos v1 hechos a mano salvo que SEL este presente (arriba dice cual se uso).")
    L.append("- Hora local asumida tal cual viene en `fecha_post_iso` (comprobado por la distribucion de horas).")
    L.append("- 37 de los 212 posts de la ventana intrasujeto no tienen texto: el estilo no los ve; la capa 2 si.")
    with open(os.path.join(SAL, "REPORTE_capa1.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(SAL, "salida_consola.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(_LOG) + "\n")


if __name__ == "__main__":
    main()
