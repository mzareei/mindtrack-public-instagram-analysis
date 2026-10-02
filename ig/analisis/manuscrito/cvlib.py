# -*- coding: utf-8 -*-
"""Vectorised re-implementation of detector_marco's estimators (identical
algorithm), shared by 03_inferencia.py and 05_sensibilidad.py."""
import math, random
import numpy as np
from scipy import stats
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ig", "control"))
import detector_marco as dm
N_BOOT, N_PERM = 2000, 1000


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


