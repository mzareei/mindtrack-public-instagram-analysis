# -*- coding: utf-8 -*-
"""
Capa 1, paso 1: convertir cada publicacion en 25 numeros, y cada cuenta en una fila.

Que se cuenta y por que (una linea por rasgo; la justificacion larga esta en
README.md de esta carpeta):

  Cuanto hablan de si mismos
    p1s_100      yo/me/mi + estoy/siento/quiero, por 100 palabras
    p1p_100      nosotros/nos, por 100 palabras
    p23_100      tu/el/ellos, por 100 palabras
  Como piensan
    absol_100    nunca/siempre/nada/todo, por 100 palabras
    neg_100      no/ni/tampoco/sin, por 100 palabras
    hedge_100    quizas/creo/no se, por 100 palabras
  Que sienten
    emo_neg_100  lexico de emocion negativa (SEL si esta, si no la v1), por 100
    emo_pos_100  lexico de emocion positiva, por 100
    muerte_100   morir/dolor/cansad*/adios, por 100
    emoji_val    valencia de emoji: (positivos - negativos) / (pos + neg), -1..1
  Como se ve el caption
    palabras_log log(1 + palabras), media por post (0 si no hay caption)
    emoji_pp     emoji por palabra
    hashtag_pp   hashtags por palabra
    mencion_pp   menciones (@) por palabra
    puntuacion   (! + ... + PALABRAS EN MAYUSCULA) por palabra
  Cuando
    noche_share  fraccion de posts entre 00:00 y 05:59 (hora local, ver abajo)
    hora_circ    hora media circular, 0-24
    finde_share  fraccion en sabado o domingo
    gap_mediana  mediana de dias entre posts consecutivos
    burstiness   desviacion / media de esos huecos (0 = regular, alto = rachas)
  Que forma
    video_share  fraccion con video
    sin_cap_share  fraccion sin caption
    solo_simb_share  fraccion cuyo caption no tiene palabras, solo emoji/hashtags
  Idioma
    ingles_share fraccion de captions con texto que estan en ingles
    diversidad   tipos / tokens sobre el texto agregado de la cuenta (NaN si <20)

Las tasas "por 100 palabras" se calculan sobre el texto AGREGADO de la cuenta
(suma de aciertos / suma de palabras), no como media de tasas por post: con
captions de 5 palabras la media de tasas es puro ruido.

Hora local. `fecha_post_iso` viene sin zona horaria. Se comprobo (9/9/2026)
que la distribucion de horas tiene su valle en 03-06 y su pico en 13-23, que es
un patron de hora LOCAL (si fuera UTC el valle caeria en 09-12). Se toma tal
cual, sin convertir.

Uso como modulo:
    from rasgos import rasgos_de_posts, NOMBRES
    fila = rasgos_de_posts(lista_de_posts)   # dict nombre -> valor (o None)
"""

import csv, math, os, re, statistics as st
import datetime as dt
from collections import Counter

DIR = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(DIR, "lexicos")

NOMBRES = [
    "p1s_100", "p1p_100", "p23_100",
    "absol_100", "neg_100", "hedge_100",
    "emo_neg_100", "emo_pos_100", "muerte_100", "emoji_val",
    "palabras_log", "emoji_pp", "hashtag_pp", "mencion_pp", "puntuacion",
    "noche_share", "hora_circ", "finde_share", "gap_mediana", "burstiness",
    "video_share", "sin_cap_share", "solo_simb_share",
    "ingles_share", "diversidad",
]
assert len(NOMBRES) == 25

# ---------------------------------------------------------------- lexicos

def _leer_lista(nombre):
    ruta = os.path.join(LEX, nombre)
    out = []
    for l in open(ruta, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#"):
            out.append(l.lower())
    return out


def _compilar(entradas):
    """Una lista de entradas -> (set de palabras exactas, lista de prefijos,
    lista de frases). Se usan asi:
      palabra exacta: token == entrada
      prefijo (termina en *): token.startswith(entrada[:-1])
      frase (tiene espacio): aparece en el texto normalizado con limites"""
    exactas, prefijos, frases = set(), [], []
    for e in entradas:
        if " " in e:
            frases.append(e)
        elif e.endswith("*"):
            prefijos.append(e[:-1])
        else:
            exactas.add(e)
    return exactas, prefijos, frases


def _cargar_sel():
    """Spanish Emotion Lexicon, si el usuario lo dejo en lexicos/SEL_full.txt.
    Formato esperado (tabulado): palabra, ..., PFA, categoria. Se lee tolerante:
    primera columna = palabra, ultima = categoria, la ultima columna numerica
    antes de la categoria = PFA. Devuelve (neg, pos) como sets o None."""
    for nombre in ("SEL_full.txt", "SEL.txt"):
        ruta = os.path.join(LEX, nombre)
        if not os.path.exists(ruta):
            continue
        neg, pos = set(), set()
        n = 0
        with open(ruta, encoding="utf-8", errors="replace") as f:
            for l in f:
                partes = [p.strip() for p in re.split(r"\t|;", l.strip()) if p.strip()]
                if len(partes) < 3:
                    continue
                palabra, cat = partes[0].lower(), partes[-1].lower()
                pfa = None
                for p in reversed(partes[1:-1]):
                    try:
                        pfa = float(p.replace(",", "."))
                        break
                    except ValueError:
                        continue
                if pfa is None or pfa < 0.5:
                    continue
                n += 1
                if cat.startswith(("enojo", "miedo", "repuls", "tristeza")):
                    neg.add(palabra)
                elif cat.startswith("alegr"):
                    pos.add(palabra)
        if n >= 100:
            return neg, pos, nombre
    return None


class Lexicos:
    def __init__(self):
        self.p1s = _compilar(_leer_lista("primera_persona_sing.txt"))
        self.p1p = _compilar(_leer_lista("primera_persona_pl.txt"))
        self.p23 = _compilar(_leer_lista("otras_personas.txt"))
        self.absol = _compilar(_leer_lista("absolutistas.txt"))
        self.neg = _compilar(_leer_lista("negaciones.txt"))
        self.hedge = _compilar(_leer_lista("hedges.txt"))
        self.muerte = _compilar(_leer_lista("muerte_dolor.txt"))
        sel = _cargar_sel()
        if sel:
            self.emo_neg = (sel[0], [], [])
            self.emo_pos = (sel[1], [], [])
            self.fuente_emocion = "SEL (%s), PFA >= 0.5: %d neg, %d pos" % (sel[2], len(sel[0]), len(sel[1]))
        else:
            self.emo_neg = _compilar(_leer_lista("emocion_negativa.txt"))
            self.emo_pos = _compilar(_leer_lista("emocion_positiva.txt"))
            self.fuente_emocion = "listas v1 hechas a mano (SEL_full.txt no encontrado en lexicos/)"
        self.emoji_neg = set(_leer_lista("emoji_negativos.txt"))
        self.emoji_pos = set(_leer_lista("emoji_positivos.txt"))
        self.ingles = set(_leer_lista("ingles.txt"))
        self.espanol = set(_leer_lista("espanol.txt"))


_LEX = None


def lexicos():
    global _LEX
    if _LEX is None:
        _LEX = Lexicos()
    return _LEX

# ---------------------------------------------------------------- tokenizacion

# Emoji: rangos amplios + variantes con selector y ZWJ. No es perfecto, es
# suficiente para contar.
_EMOJI = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}|"
    "[\U0001F300-\U0001FAFF☀-➿⬀-⯿\U0001F000-\U0001F2FF]"
    "(?:[️\U0001F3FB-\U0001F3FF])?(?:‍[\U0001F300-\U0001FAFF☀-➿](?:️)?)*)")
_HASHTAG = re.compile(r"#\w+")
_MENCION = re.compile(r"@[\w.]+")
_PALABRA = re.compile(r"[a-záéíóúüñ]+(?:'[a-z]+)?", re.I)
_MAYUS = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{3,}\b")


def normalizar(texto):
    t = (texto or "").replace("’", "'").replace("“", '"').replace("”", '"')
    return t


def contar_hits(tokens, texto_norm, lex):
    exactas, prefijos, frases = lex
    n = sum(1 for t in tokens if t in exactas)
    if prefijos:
        n += sum(1 for t in tokens if any(t.startswith(p) for p in prefijos) and t not in exactas)
    for fr in frases:
        n += len(re.findall(r"(?<!\w)" + re.escape(fr) + r"(?!\w)", texto_norm))
    return n


def analizar_post(post):
    """Cuenta todo lo contable en un post. Devuelve un dict de conteos crudos
    (no tasas): la agregacion por cuenta los combina."""
    L = lexicos()
    cap = normalizar(post.get("caption") or "")
    sin_hashtags = _HASHTAG.sub(" ", cap)
    sin_menciones = _MENCION.sub(" ", sin_hashtags)
    texto = sin_menciones
    texto_l = texto.lower()
    tokens = [t.lower() for t in _PALABRA.findall(texto)]
    n_pal = len(tokens)
    emojis = _EMOJI.findall(cap)
    emojis = [e for e in emojis if e.strip()]
    hashtags = _HASHTAG.findall(cap)
    menciones = _MENCION.findall(cap)

    c = {
        "palabras": n_pal,
        "tokens": tokens,
        "p1s": contar_hits(tokens, texto_l, L.p1s),
        "p1p": contar_hits(tokens, texto_l, L.p1p),
        "p23": contar_hits(tokens, texto_l, L.p23),
        "absol": contar_hits(tokens, texto_l, L.absol),
        "neg": contar_hits(tokens, texto_l, L.neg),
        "hedge": contar_hits(tokens, texto_l, L.hedge),
        "emo_neg": contar_hits(tokens, texto_l, L.emo_neg),
        "emo_pos": contar_hits(tokens, texto_l, L.emo_pos),
        "muerte": contar_hits(tokens, texto_l, L.muerte),
        "emoji": len(emojis),
        "emoji_neg": sum(1 for e in emojis if e in L.emoji_neg or e.replace("️", "") in L.emoji_neg),
        "emoji_pos": sum(1 for e in emojis if e in L.emoji_pos or e.replace("️", "") in L.emoji_pos),
        "hashtags": len(hashtags),
        "menciones": len(menciones),
        "exclam": cap.count("!") + cap.count("¡"),
        "puntos": len(re.findall(r"\.{3,}|…", cap)),
        "mayus": len(_MAYUS.findall(texto)),
        "sin_caption": 1 if not cap.strip() else 0,
        "solo_simbolos": 1 if (cap.strip() and n_pal == 0) else 0,
        "video": 1 if (post.get("video_url") or post.get("video_local")) else 0,
    }
    # idioma del caption (solo si tiene texto)
    if n_pal >= 2:
        en = sum(1 for t in tokens if t in L.ingles)
        es = sum(1 for t in tokens if t in L.espanol)
        c["ingles"] = 1 if (en >= 2 and en > es) else 0
        c["tiene_texto"] = 1
    else:
        c["ingles"] = 0
        c["tiene_texto"] = 1 if n_pal >= 1 else 0
    # tiempo
    f = post.get("fecha_post_iso") or post.get("fecha") or ""
    try:
        d = dt.datetime.fromisoformat(str(f)[:19])
        c["fecha"] = d
        c["hora"] = d.hour + d.minute / 60.0
        c["noche"] = 1 if d.hour < 6 else 0
        c["finde"] = 1 if d.weekday() >= 5 else 0
    except ValueError:
        c["fecha"] = None
        c["hora"] = None
        c["noche"] = None
        c["finde"] = None
    return c


def _tasa(num, den, por=100.0):
    return (por * num / den) if den else None


def rasgos_de_posts(posts):
    """Lista de posts (dicts del global) -> dict con los 25 rasgos de la cuenta.
    None donde no se puede calcular (se imputa despues, en el modelo)."""
    cs = [analizar_post(p) for p in posts]
    n = len(cs)
    if n == 0:
        return {k: None for k in NOMBRES}
    pal = sum(c["palabras"] for c in cs)
    con_texto = [c for c in cs if c["tiene_texto"]]
    r = {}
    r["p1s_100"] = _tasa(sum(c["p1s"] for c in cs), pal)
    r["p1p_100"] = _tasa(sum(c["p1p"] for c in cs), pal)
    r["p23_100"] = _tasa(sum(c["p23"] for c in cs), pal)
    r["absol_100"] = _tasa(sum(c["absol"] for c in cs), pal)
    r["neg_100"] = _tasa(sum(c["neg"] for c in cs), pal)
    r["hedge_100"] = _tasa(sum(c["hedge"] for c in cs), pal)
    r["emo_neg_100"] = _tasa(sum(c["emo_neg"] for c in cs), pal)
    r["emo_pos_100"] = _tasa(sum(c["emo_pos"] for c in cs), pal)
    r["muerte_100"] = _tasa(sum(c["muerte"] for c in cs), pal)
    ep, en = sum(c["emoji_pos"] for c in cs), sum(c["emoji_neg"] for c in cs)
    r["emoji_val"] = ((ep - en) / float(ep + en)) if (ep + en) else None
    r["palabras_log"] = st.mean(math.log1p(c["palabras"]) for c in cs)
    r["emoji_pp"] = sum(c["emoji"] for c in cs) / float(pal + n)
    r["hashtag_pp"] = sum(c["hashtags"] for c in cs) / float(pal + n)
    r["mencion_pp"] = sum(c["menciones"] for c in cs) / float(pal + n)
    r["puntuacion"] = sum(c["exclam"] + c["puntos"] + c["mayus"] for c in cs) / float(pal + n)
    con_hora = [c for c in cs if c["hora"] is not None]
    if con_hora:
        r["noche_share"] = st.mean(c["noche"] for c in con_hora)
        r["finde_share"] = st.mean(c["finde"] for c in con_hora)
        sx = sum(math.cos(2 * math.pi * c["hora"] / 24.0) for c in con_hora)
        sy = sum(math.sin(2 * math.pi * c["hora"] / 24.0) for c in con_hora)
        ang = math.atan2(sy, sx)
        r["hora_circ"] = (ang / (2 * math.pi) * 24.0) % 24.0
        fechas = sorted(c["fecha"] for c in con_hora)
        gaps = [(b - a).total_seconds() / 86400.0 for a, b in zip(fechas, fechas[1:])]
        gaps = [g for g in gaps if g >= 0]
        r["gap_mediana"] = st.median(gaps) if gaps else None
        r["burstiness"] = (st.pstdev(gaps) / st.mean(gaps)) if (len(gaps) >= 3 and st.mean(gaps) > 0) else None
    else:
        r["noche_share"] = r["finde_share"] = r["hora_circ"] = r["gap_mediana"] = r["burstiness"] = None
    r["video_share"] = st.mean(c["video"] for c in cs)
    r["sin_cap_share"] = st.mean(c["sin_caption"] for c in cs)
    r["solo_simb_share"] = st.mean(c["solo_simbolos"] for c in cs)
    r["ingles_share"] = (st.mean(c["ingles"] for c in con_texto)) if con_texto else None
    toks = [t for c in cs for t in c["tokens"]]
    r["diversidad"] = (len(set(toks)) / float(len(toks))) if len(toks) >= 20 else None
    r["_n_posts"] = n
    r["_n_palabras"] = pal
    return r


def fila_post(post, extra=None):
    """Una fila por post para inspeccion (sin texto: solo conteos)."""
    c = analizar_post(post)
    fila = {k: c[k] for k in ("palabras", "p1s", "p1p", "p23", "absol", "neg", "hedge",
                              "emo_neg", "emo_pos", "muerte", "emoji", "emoji_neg",
                              "emoji_pos", "hashtags", "menciones", "exclam", "puntos",
                              "mayus", "sin_caption", "solo_simbolos", "video", "ingles")}
    fila["hora"] = round(c["hora"], 2) if c["hora"] is not None else ""
    fila["noche"] = c["noche"] if c["noche"] is not None else ""
    fila["finde"] = c["finde"] if c["finde"] is not None else ""
    fila["fecha"] = c["fecha"].date().isoformat() if c["fecha"] else ""
    if extra:
        fila.update(extra)
    return fila


def autoprueba():
    """Casos mínimos para no publicar un contador roto."""
    L = lexicos()
    p = {"caption": "Ya no puedo más... estoy cansada de todo 🖤🥀 #reflexión", "fecha_post_iso": "2026-03-01T02:30:00"}
    c = analizar_post(p)
    ok = True
    def chk(cond, msg):
        nonlocal ok
        print(("  OK    " if cond else "  FALLO ") + msg)
        ok = ok and cond
    chk(c["palabras"] == 8, "palabras=8 (%d)" % c["palabras"])
    chk(c["p1s"] >= 2, "p1s cuenta 'puedo' y 'estoy' (%d)" % c["p1s"])
    chk(c["absol"] == 1, "absol cuenta 'todo' (%d)" % c["absol"])
    chk(c["neg"] == 1, "neg cuenta 'no' (%d)" % c["neg"])
    chk(c["muerte"] >= 2, "muerte cuenta 'ya no', 'no puedo mas', 'cansad*' (%d)" % c["muerte"])
    chk(c["emoji"] == 2 and c["emoji_neg"] == 2, "emoji 2, negativos 2 (%d, %d)" % (c["emoji"], c["emoji_neg"]))
    chk(c["hashtags"] == 1, "hashtag 1 (%d)" % c["hashtags"])
    chk(c["puntos"] == 1, "puntos suspensivos 1 (%d)" % c["puntos"])
    chk(c["noche"] == 1, "02:30 es noche")
    p2 = {"caption": "the best day with my friends ❤️", "fecha_post_iso": "2026-03-07T20:00:00"}
    c2 = analizar_post(p2)
    chk(c2["ingles"] == 1, "caption en ingles detectado")
    chk(c2["finde"] == 1, "sabado es finde")
    chk(c2["emoji_pos"] == 1, "corazon rojo positivo (%d)" % c2["emoji_pos"])
    p3 = {"caption": "", "fecha_post_iso": "2026-03-07T20:00:00"}
    chk(analizar_post(p3)["sin_caption"] == 1, "sin caption")
    p4 = {"caption": "✨✨ #vibes", "fecha_post_iso": "2026-03-07T20:00:00"}
    chk(analizar_post(p4)["solo_simbolos"] == 1, "solo simbolos")
    r = rasgos_de_posts([p, p2, p3, p4])
    chk(all(k in r for k in NOMBRES), "los 25 rasgos estan")
    print("  fuente de emocion: %s" % L.fuente_emocion)
    print("\n  RESULTADO:", "OK" if ok else "REVISAR")
    return ok


if __name__ == "__main__":
    autoprueba()
