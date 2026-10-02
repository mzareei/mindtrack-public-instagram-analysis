# -*- coding: utf-8 -*-
"""
Capa 1, paso 2: ¿el estilo separa pacientes de controles?

Entrada: una fila por cuenta con los 25 rasgos (de rasgos.py), 30 pacientes y
los 60 controles emparejados.

Que hace:
  1. Imputa los huecos con la mediana de cada rasgo (los huecos existen:
     diversidad con <20 palabras, burstiness con <3 posts, emoji_val sin emoji
     con valencia). Se reporta cuantos hubo.
  2. AUC univariada de cada rasgo + prueba de Mann-Whitney + FDR. Dice que
     rasgos, uno a uno, distinguen a los grupos.
  3. Regresion logistica con los 25 juntos, validacion cruzada estratificada
     repetida (la misma de detector_marco.py, misma semilla, misma
     regularizacion). Un perfil = una persona, asi que la CV ya agrupa por
     persona.
  4. Opcional (--permutaciones N): baraja las etiquetas N veces y repite la CV
     para saber si el AUC observado sale por azar. Lento en Python puro
     (~1 s por ajuste); 100 permutaciones ~ 10 min.

La referencia contra la que se lee el AUC es la del detector de marco (solo
metadatos): 0.439 el 9/9/2026. Si el estilo no pasa claramente de ahi, no hay
señal de estilo que reclamar.

Uso como modulo desde correr_capa1.py. Suelto:
    python ig/analisis/estilo/entre_personas.py rasgos_cuentas.csv [--permutaciones 100]
"""

import csv, math, os, random, sys, statistics as st

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(DIR)), "control"))
from rasgos import NOMBRES
from estadistica import mann_whitney_p, bh_fdr
import detector_marco as dm


def imputar(filas, nombres):
    """Mediana por columna. Devuelve (X, n_imputados_por_columna)."""
    X = [[f.get(n) for n in nombres] for f in filas]
    imput = {}
    for j, n in enumerate(nombres):
        col = [x[j] for x in X if x[j] is not None and x[j] == x[j]]
        med = st.median(col) if col else 0.0
        k = 0
        for x in X:
            if x[j] is None or x[j] != x[j]:
                x[j] = med
                k += 1
        imput[n] = k
    return X, imput


def univariadas(X, y, nombres):
    out = []
    for j, n in enumerate(nombres):
        col = [x[j] for x in X]
        a = dm.auc(y, col)
        a1 = [c for c, yy in zip(col, y) if yy == 1]
        a0 = [c for c, yy in zip(col, y) if yy == 0]
        p = mann_whitney_p(a1, a0)
        out.append({"rasgo": n, "auc": a, "mediana_pacientes": st.median(a1),
                    "mediana_controles": st.median(a0), "p": p,
                    "direccion": "pacientes >" if st.median(a1) > st.median(a0) else
                                 ("pacientes <" if st.median(a1) < st.median(a0) else "=")})
    qs = bh_fdr([o["p"] for o in out])
    for o, q in zip(out, qs):
        o["q_fdr"] = q
    return sorted(out, key=lambda o: -abs(o["auc"] - 0.5))


def multivariada(X, y, repeticiones=20):
    return dm.cv_auc(X, y, k=5, repeticiones=repeticiones)


def permutaciones(X, y, n_perm, auc_obs, semilla=20260910, log=print):
    """p-valor del AUC multivariado por barajado de etiquetas. Ajustes mas
    cortos (menos iteraciones) para que sea viable en Python puro; el AUC
    observado se recalcula con los MISMOS parametros para que la comparacion
    sea justa."""
    rng = random.Random(semilla)
    iters_orig = dm.entrenar.__defaults__
    # entrenar(X, y, iters=3000, lr=0.1, l2=1.0) -> acortamos iters
    dm.entrenar.__defaults__ = (600, 0.1, 1.0)
    try:
        obs, _, _, _ = dm.cv_auc(X, y, k=5, repeticiones=2, semilla=semilla)
        mayores = 0
        for i in range(n_perm):
            yp = list(y)
            rng.shuffle(yp)
            a, _, _, _ = dm.cv_auc(X, yp, k=5, repeticiones=2, semilla=semilla + i)
            if a >= obs:
                mayores += 1
            if (i + 1) % 10 == 0:
                log("    permutacion %d/%d  (AUC obs %.3f, nulos >= obs: %d)" % (i + 1, n_perm, obs, mayores))
    finally:
        dm.entrenar.__defaults__ = iters_orig
    return (mayores + 1) / float(n_perm + 1), obs


def coeficientes(X, y, nombres):
    Xs, mu, sd = dm._estandarizar(X)
    w, b = dm.entrenar(Xs, y)
    return sorted(zip(nombres, w), key=lambda t: -abs(t[1]))


def correr(filas, nombres=NOMBRES, n_perm=0, referencia_marco=None, log=print):
    y = [1 if f.get("grupo") == "paciente" else 0 for f in filas]
    X, imput = imputar(filas, nombres)
    res = {"n": len(y), "n_pacientes": sum(y), "n_controles": len(y) - sum(y),
           "imputados": {k: v for k, v in imput.items() if v}}
    log("\nENTRE PERSONAS: estilo de %d pacientes vs %d controles, %d rasgos"
        % (sum(y), len(y) - sum(y), len(nombres)))
    if res["imputados"]:
        log("  huecos imputados con la mediana: " + ", ".join("%s=%d" % kv for kv in res["imputados"].items()))
    uni = univariadas(X, y, nombres)
    res["univariadas"] = uni
    log("\n  Rasgo a rasgo (AUC univariada; >0.5 = mas en pacientes; q = FDR):")
    log("  %-16s %6s %10s %10s %8s %8s  %s" % ("rasgo", "AUC", "med.pac", "med.ctrl", "p", "q", ""))
    for o in uni:
        marca = " <-- q<0.05" if o["q_fdr"] == o["q_fdr"] and o["q_fdr"] < 0.05 else (" (p<0.05)" if o["p"] < 0.05 else "")
        log("  %-16s %6.3f %10.3f %10.3f %8.3f %8.3f%s" % (o["rasgo"], o["auc"], o["mediana_pacientes"], o["mediana_controles"], o["p"], o["q_fdr"], marca))
    a, disp, ys, ps = multivariada(X, y)
    res["auc_cv"], res["auc_cv_de"] = a, disp
    log("\n  Los 25 juntos, regresion logistica, CV 5x20:")
    log("    AUC = %.3f  (DE entre repeticiones %.3f)" % (a, disp))
    if referencia_marco is not None:
        res["referencia_marco"] = referencia_marco
        log("    referencia, detector de marco (solo metadatos): %.3f" % referencia_marco)
        log("    diferencia: %+.3f" % (a - referencia_marco))
    coef = coeficientes(X, y, nombres)
    res["coeficientes"] = coef
    log("\n  Que pesa mas en el modelo conjunto (coeficiente estandarizado):")
    for n, w in coef[:8]:
        log("    %-16s %+.3f" % (n, w))
    if n_perm:
        log("\n  Permutaciones (%d, ajustes cortos):" % n_perm)
        p_perm, obs_corto = permutaciones(X, y, n_perm, a, log=log)
        res["p_permutacion"], res["auc_perm_obs"] = p_perm, obs_corto
        log("    AUC observado con ajustes cortos: %.3f   p = %.3f" % (obs_corto, p_perm))
    return res


def main():
    ruta = [a for a in sys.argv[1:] if a.endswith(".csv")]
    if not ruta:
        sys.exit(__doc__)
    filas = []
    for r in csv.DictReader(open(ruta[0], encoding="utf-8-sig")):
        f = {"grupo": r["grupo"]}
        for n in NOMBRES:
            v = r.get(n, "")
            f[n] = float(v) if v not in ("", None) else None
        filas.append(f)
    n_perm = int(sys.argv[sys.argv.index("--permutaciones") + 1]) if "--permutaciones" in sys.argv else 0
    correr(filas, n_perm=n_perm)


if __name__ == "__main__":
    main()
