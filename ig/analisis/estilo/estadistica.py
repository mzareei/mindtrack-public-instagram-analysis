# -*- coding: utf-8 -*-
"""
Pruebas en Python puro para la capa 1. Sin numpy ni scipy: el venv del
proyecto no los tiene y no se van a añadir por esto.

  mann_whitney_p(a, b)     dos muestras independientes, aprox. normal con
                           correccion por empates. Para 30 vs 60 es adecuada.
  wilcoxon_p(d)            signed-rank pareado, aprox. normal con correccion de
                           continuidad; ceros fuera. Para n=18 es aceptable;
                           se reporta junto al signo exacto.
  signo_p(sube, baja)      prueba de signos exacta (binomial, dos colas).
  bh_fdr(ps)               Benjamini-Hochberg: lista de q-values, mismo orden.
  mediana(xs)              tolera lista vacia.
"""

import math
import statistics as st


def _phi_dos_colas(z):
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def _rangos(vals):
    orden = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    i = 0
    empates = []
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and vals[orden[j + 1]] == vals[orden[i]]:
            j += 1
        rango = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[orden[k]] = rango
        if j > i:
            empates.append(j - i + 1)
        i = j + 1
    return r, empates


def mann_whitney_p(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return float("nan")
    r, empates = _rangos(list(a) + list(b))
    r1 = sum(r[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    n = n1 + n2
    corr = sum(t ** 3 - t for t in empates) / (n * (n - 1)) if n > 1 else 0.0
    var = n1 * n2 / 12.0 * ((n + 1) - corr)
    if var <= 0:
        return 1.0
    z = (u1 - mu) / math.sqrt(var)
    return _phi_dos_colas(z)


def wilcoxon_p(d):
    d = [x for x in d if x != 0]
    n = len(d)
    if n < 5:
        return float("nan")
    r, empates = _rangos([abs(x) for x in d])
    w_pos = sum(ri for ri, x in zip(r, d) if x > 0)
    mu = n * (n + 1) / 4.0
    var = n * (n + 1) * (2 * n + 1) / 24.0 - sum(t ** 3 - t for t in empates) / 48.0
    if var <= 0:
        return 1.0
    z = (w_pos - mu - 0.5 * (1 if w_pos > mu else -1)) / math.sqrt(var)
    return _phi_dos_colas(z)


def signo_p(sube, baja):
    m = sube + baja
    if m == 0:
        return float("nan")
    k = min(sube, baja)
    return min(1.0, 2.0 * sum(math.comb(m, i) for i in range(k + 1)) / 2.0 ** m)


def bh_fdr(ps):
    idx = [i for i, p in enumerate(ps) if p == p]
    m = len(idx)
    if not m:
        return [float("nan")] * len(ps)
    orden = sorted(idx, key=lambda i: ps[i])
    q = [float("nan")] * len(ps)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = orden[rank - 1]
        val = min(prev, ps[i] * m / rank)
        q[i] = val
        prev = val
    return q


def mediana(xs):
    xs = [x for x in xs if x is not None and x == x]
    return st.median(xs) if xs else float("nan")
