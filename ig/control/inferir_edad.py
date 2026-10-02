# -*- coding: utf-8 -*-
"""
Inferencia de edad para cuentas publicas de Instagram (grupo control MindTrack).

No adivina la edad de todo el mundo. Devuelve una estimacion SOLO cuando hay una
señal explicita en el texto que la persona misma escribio, y dice de que señal se
trata y con cuanta confianza. Todo lo demas sale como confianza "nula" y esa
cuenta NO entra al grupo control.

Decisiones de diseño, con su razon:

  - NO se usa la foto de perfil. Estimar edad de una cara es tratamiento de datos
    biometricos de una persona que no consintio. Ningun comite lo aprueba y no
    hace falta.
  - NO se usan marcadores de fandom, tipografia decorativa ni jerga como señal de
    edad, aunque correlacionan. Estan confundidos con el constructo clinico: si
    filtras controles por "escribe como adolescente" acabas seleccionando
    justamente el estilo que el modelo de riesgo va a leer despues.
  - La antiguedad de la cuenta da una COTA INFERIOR de edad, no una estimacion.
    Se usa solo para descartar imposibles, nunca para fijar la edad.
  - Las biografias envejecen. Una edad escrita en la bio hace dos años sigue
    diciendo el numero viejo. El error medido contra los pacientes esta en la
    seccion de validacion; hay que reportarlo, no esconderlo.

Uso:
    python ig/control/inferir_edad.py --validar
        Corre contra los 30 pacientes con edad conocida del dataset e imprime
        cobertura, error absoluto medio y acierto de banda. Esta es la cifra de
        calibracion que hay que citar en el articulo.

    python ig/control/inferir_edad.py --global resultados_ig/global_XXXX.json
        Corre sobre una corrida de candidatos y escribe candidatos_edad.csv.
"""

import re, csv, json, os, sys, unicodedata
from datetime import date, datetime

ANIO_ACTUAL = date.today().year

# Rango del estudio. Fuera de esto la cuenta se descarta.
EDAD_MIN, EDAD_MAX = 15, 29

BANDAS = ((15, 17), (18, 21), (22, 25), (26, 29))

# Edad minima plausible para abrir una cuenta. Se usa para la cota inferior a
# partir de la antiguedad de la cuenta: alguien que publica desde 2014 no puede
# tener 15 años hoy.
EDAD_MIN_APERTURA = 10

# Texto que Instagram mete dentro del bloque de biografia y que NO escribio la
# persona. Si no se quita, "Followed by usuario_ejemplo20" aporta un "19" que no es de
# nadie. (Ojo: esto tambien contamina perfiles.csv de la corrida de pacientes.)
RUIDO_UI = (
    r"Followed by .*$",
    r"Seguido por .*$",
    r"\.\.\.\s*more$",
    r"\.\.\.\s*mas$",
)

FULLWIDTH = {chr(0xFF10 + i): str(i) for i in range(10)}

SUPERINDICES = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
}


def _quitar_categoria(texto):
    """La primera linea de una cuenta profesional es la etiqueta que pone
    Instagram ("Digital creator", "Mexican Restaurant"). No la escribio la
    persona, asi que no puede aportar su edad."""
    try:
        from util import categoria_profesional
    except ImportError:
        return texto
    cat = categoria_profesional(texto)
    if cat and texto:
        i = texto.lower().find(cat.lower())
        if i != -1:
            return texto[:i] + texto[i + len(cat):]
    return texto


def _normalizar(texto):
    """Deja el texto listo para buscar numeros: quita el ruido de UI, los
    handles, las URLs y pasa los superindices y las variantes tipograficas de
    digito a digitos normales."""
    if not texto:
        return ""
    t = _quitar_categoria(texto)
    for patron in RUIDO_UI:
        t = re.sub(patron, " ", t, flags=re.IGNORECASE | re.MULTILINE)
    # Superindices (¹⁷ = 17, caso real en el corpus) y digitos de ancho
    # completo -> ASCII.
    # OJO: NO se convierte cualquier digito Unicode con unicodedata.digit().
    # Los adornos decorativos de las bios adolescentes usan digitos de otros
    # alfabetos: "✩┈┈∘*┈୨୧┈*∘┈┈✩" lleva ୨୧, que son el 2 y el 1 en odia, y se
    # leian como "21 años" en un perfil de 17. Solo se convierte lo que la
    # gente usa DE VERDAD para escribir su edad.
    t = "".join(SUPERINDICES.get(c, c) for c in t)
    t = "".join(FULLWIDTH.get(c, c) for c in t)
    # @handles y URLs fuera: "usuario_ejemplo20" y "usuario_ejemplo11" no son edades.
    t = re.sub(r"@[\w.]+", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    # "22Años", "17yo", "23歳" van pegados y NO son handles: separarlos antes
    # de limpiar tokens con letras y digitos mezclados. (Caso real: usuario_ejemplo15,
    # "Tapatío 22Años", se perdia.)
    t = re.sub(r"(?<![0-9A-Za-z])([0-9]{2})(?=(?:a[nñ]os|anios|anos|años|yo|y/o|years|歳)\b)", r"\1 ", t, flags=re.I)
    # Tokens tipo handle: letras+digitos pegados, o con _ o . seguido de digitos
    # (nombre de pantalla "usuario_ejemplo12" -> el "_24" no es una edad).
    t = re.sub(r"\S*[._][0-9]+\S*", " ", t)
    t = re.sub(r"\b\w*[a-zA-Z]+[0-9]+\w*\b", " ", t)
    t = re.sub(r"\b[0-9]+[a-zA-Z]+\w*\b", " ", t)
    return t


def _fechas_a_enmascarar(texto):
    """Las fechas tipo 18.07.21 o 16/02/24 son cumpleaños de hijos, aniversarios
    o fechas de un negocio. Nunca son la edad de nadie. Se tapan antes de buscar
    numeros sueltos. (Caso real: MINDxxxx, dos fechas de nacimiento de sus hijas
    en la bio.)"""
    # Fechas dd.mm.aa
    t = re.sub(r"\b[0-9]{1,2}[./\-][0-9]{1,2}[./\-][0-9]{2,4}\b", " ", texto)
    # Horas y numeros de angel: "1:11", "11:11", "22:22". Muy comunes en bios
    # de adolescentes y se leian como edad.
    t = re.sub(r"\b[0-9]{1,2}:[0-9]{2}\b", " ", t)
    # Precios: "pines personalizables a $25", "3x2", "$150". Las cuentas que
    # venden algo meten cifras por todas partes. Caso real del piloto:
    # usuario_ejemplo9 se aprobo como persona de 25 años por un precio de $25.
    t = re.sub(r"[$€]\s*[0-9]+(?:[.,][0-9]+)?", " ", t)
    t = re.sub(r"\b[0-9]+\s*[xX]\s*[0-9]+\b", " ", t)
    # Descuentos y porcentajes.
    t = re.sub(r"\b[0-9]+\s*%", " ", t)
    # Numeros de escuela y de curso: "Prepa 15", "Preparatoria No. 12",
    # "Secundaria 8", "4to semestre", "semestre 6". (Caso real: usuario_ejemplo6,
    # "Prepa 15" se leyo como 15 años.)
    t = re.sub(r"\b(?:prepa|preparatoria|secundaria|secu|escuela|primaria|modulo|m[oó]dulo|"
               r"regional|bachillerato|vocacional|cbtis|conalep|cecytej|cetis|cu)"
               r"\s*(?:no\.?|n[°º•]?|#)?\s*[0-9]{1,2}\b", " ", t, flags=re.I)
    t = re.sub(r"\b[0-9]{1,2}\s*(?:er|do|to|vo|mo|°|º)?\s*semestre\b", " ", t, flags=re.I)
    t = re.sub(r"\bsemestre\s*[0-9]{1,2}\b", " ", t, flags=re.I)
    return t


def señal_edad_explicita(bio, nombre=""):
    """Edad escrita como numero suelto o con la palabra al lado."""
    # Muchos ponen su propio handle como nombre de pantalla. Un nombre con
    # "_" o "." o digitos pegados no aporta edad, aporta ruido.
    if nombre and re.search(r"[._]|[a-zA-Z][0-9]|[0-9][a-zA-Z]", nombre):
        nombre = ""
    t = _fechas_a_enmascarar(_normalizar(" ".join([bio or "", nombre or ""])))

    # 1) Con palabra explicita: "23 años", "23 years old", "23 y/o".
    m = re.search(r"(?<![0-9])([0-9]{2})\s*(?:años|anios|anos|years?\s*old|y/?o|歳)(?![a-z])", t, re.I)
    if m:
        e = int(m.group(1))
        if EDAD_MIN - 3 <= e <= EDAD_MAX + 5:
            return e, "alta", "edad con palabra: %r" % m.group(0).strip()

    # 2) Numero suelto de dos digitos en rango, delimitado por separadores de
    #    bio (| // salto de linea, emoji, principio o fin). Un numero suelto en
    #    medio de una frase es casi siempre otra cosa.
    # Delimitador = cualquier caracter que no sea letra ni digito. En las bios
    # reales de Instagram el separador casi nunca es "|": es un emoji. Con el
    # conjunto estrecho anterior, "Gdl, Mexico 26<emoji>" no se detectaba, y en
    # el piloto del 2 sep eso dejo la cobertura en CERO.
    for m in re.finditer(r"(?:^|[^0-9A-Za-zÀ-ÿ])([0-9]{2})(?:[^0-9A-Za-zÀ-ÿ]|$)", t):
        e = int(m.group(1))
        if EDAD_MIN - 2 <= e <= EDAD_MAX + 2:
            return e, "media", "numero suelto en bio: %r" % m.group(0).strip()
    return None, "nula", ""


def señal_anio_nacimiento(bio, usuario=""):
    """Año de nacimiento de cuatro digitos en la bio. En el usuario NO se busca:
    'usuario_ejemplo13' o 'usuario_ejemplo18' generan basura."""
    t = _fechas_a_enmascarar(_normalizar(bio))
    for m in re.finditer(r"\b(19[89][0-9]|20[0-2][0-9])\b", t):
        anio = int(m.group(1))
        e = ANIO_ACTUAL - anio
        if EDAD_MIN - 2 <= e <= EDAD_MAX + 2:
            return e, "media", "año de nacimiento en bio: %s" % anio
    return None, "nula", ""


# Marcadores de nivel escolar. Dan una BANDA, no una edad puntual.
NIVEL_ESCOLAR = (
    (r"\b(secundaria|secu|telesecundaria)\b", (12, 15), "secundaria"),
    (r"\b(prepa|preparatoria|bachillerato|cbtis|conalep|cecytej|cetis|vocacional)\b",
     (15, 18), "preparatoria"),
    (r"\b(universidad|licenciatura|lic\.?|ingenieria|udg|cucei|cucsh|cucs|cucea|"
     r"cutonala|cusur|itesm|tec de monterrey|uteg|univa|unam|ipn|upn)\b",
     (18, 24), "superior"),
    (r"\b(maestria|posgrado|doctorado)\b", (23, 30), "posgrado"),
)


def señal_nivel_escolar(bio):
    t = _normalizar(bio).lower()
    for patron, (lo, hi), etiqueta in NIVEL_ESCOLAR:
        if re.search(patron, t, re.I):
            return (lo + hi) // 2, (lo, hi), "baja", "nivel escolar: %s" % etiqueta
    return None, None, "nula", ""


def señal_generacion(bio, captions=()):
    """'gen 2026', 'generacion 26', '#generacion2026'. En Mexico la generacion de
    egreso de prepa fija la edad con poco margen: quien egresa de prepa en 2026
    tiene 17-19 hoy."""
    # Los captions pueden venir con None dentro (posts sin texto): hay que
    # colarlos antes de unirlos o revienta el join.
    textos = [bio or ""] + [c for c in (captions or []) if isinstance(c, str)]
    t = _normalizar(" ".join(textos)).lower()
    m = re.search(r"\b(?:gen|generaci[oó]n)\s*\.?\s*'?([0-9]{2}|20[0-9]{2})\b", t)
    if not m:
        return None, None, "nula", ""
    crudo = m.group(1)
    anio = int(crudo) if len(crudo) == 4 else 2000 + int(crudo)
    if not (2015 <= anio <= ANIO_ACTUAL + 4):
        return None, None, "nula", ""
    # Egreso de prepa a los 18 +/- 1.
    edad = 18 + (ANIO_ACTUAL - anio)
    return edad, (edad - 2, edad + 2), "baja", "generacion %d" % anio


def cota_inferior_por_antiguedad(fecha_primer_post):
    """Si la cuenta publica desde 2014, la persona tiene al menos
    EDAD_MIN_APERTURA + (hoy - 2014) años. Es una COTA, no una estimacion, y
    puede fallar si la cuenta se heredo o se reciclo."""
    if not fecha_primer_post:
        return None, ""
    try:
        anio = datetime.fromisoformat(str(fecha_primer_post)).year
    except (ValueError, TypeError):
        return None, ""
    cota = EDAD_MIN_APERTURA + (ANIO_ACTUAL - anio)
    return cota, "publica desde %d -> edad >= %d" % (anio, cota)


def banda_de(edad):
    for lo, hi in BANDAS:
        if lo <= edad <= hi:
            return "%d-%d" % (lo, hi)
    return "fuera"


def inferir(bio="", nombre="", usuario="", captions=(), fecha_primer_post=None):
    """Devuelve un dict con la estimacion y toda la evidencia que la sostiene.

    confianza:
      alta  -> edad escrita con la palabra al lado. Entra al control.
      media -> numero suelto en bio o año de nacimiento. Entra al control.
      baja  -> solo banda por nivel escolar o generacion. Entra SOLO si se
               acepta trabajar por bandas; marcar en la tabla del articulo.
      nula  -> no hay señal. NO entra al control.
    """
    señales = []

    e1, c1, ev1 = señal_edad_explicita(bio, nombre)
    if e1:
        señales.append((e1, None, c1, ev1))
    e2, c2, ev2 = señal_anio_nacimiento(bio, usuario)
    if e2:
        señales.append((e2, None, c2, ev2))
    e3, r3, c3, ev3 = señal_generacion(bio, captions)
    if e3:
        señales.append((e3, r3, c3, ev3))
    e4, r4, c4, ev4 = señal_nivel_escolar(bio)
    if e4:
        señales.append((e4, r4, c4, ev4))

    cota, ev_cota = cota_inferior_por_antiguedad(fecha_primer_post)

    orden = {"alta": 3, "media": 2, "baja": 1}
    señales.sort(key=lambda s: -orden.get(s[2], 0))

    res = {
        "edad_estimada": None, "rango": None, "banda": None,
        "confianza": "nula", "evidencia": "", "señales": [s[3] for s in señales],
        "cota_inferior": cota, "conflicto": "",
    }
    if ev_cota:
        res["señales"].append(ev_cota)

    if not señales:
        return res

    edad, rango, conf, ev = señales[0]

    # La cota manda sobre una estimacion imposible: si la bio dice 15 pero la
    # cuenta publica desde 2013, una de las dos cosas es falsa. Se marca y se
    # baja la confianza en vez de creerle a ciegas a la bio.
    if cota and edad < cota - 1:
        res["conflicto"] = "bio dice %d pero %s" % (edad, ev_cota)
        conf = "baja" if conf != "baja" else "nula"

    # Dos señales independientes que coinciden en +/-2 suben la confianza.
    if len(señales) > 1 and señales[1][0] and abs(señales[1][0] - edad) <= 2:
        conf = "alta" if conf == "media" else conf

    res.update({
        "edad_estimada": edad,
        "rango": rango or (edad - 1, edad + 1),
        "banda": banda_de(edad),
        "confianza": conf,
        "evidencia": ev,
    })
    return res


def en_rango_estudio(res, aceptar_baja=False):
    """Criterio de admision al grupo control."""
    if res["confianza"] == "nula":
        return False
    if res["confianza"] == "baja" and not aceptar_baja:
        return False
    e = res["edad_estimada"]
    return e is not None and EDAD_MIN <= e <= EDAD_MAX


# VALIDACION CONTRA LOS PACIENTES
# Los 30 pacientes con cuenta publica y posts son el unico conjunto donde se
# conoce la edad real y la biografia al mismo tiempo. Es el patron de oro
# disponible para calibrar. Es pequeño y es clinico, asi que la cobertura medida
# aqui es orientativa, pero el sesgo de las biografias viejas si es real.

def _ruta(*partes):
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, *partes)


def validar(ruta_perfiles=None, ruta_dataset=None, ruta_posts=None):
    ruta_perfiles = ruta_perfiles or _ruta("resultados_ig", "extraccion", "perfiles.csv")
    ruta_posts = ruta_posts or _ruta("resultados_ig", "extraccion", "posts.csv")
    if not ruta_dataset:
        for cand in (_ruta("mindtrack_dataset_v1.csv"),
                     _ruta("..", "Rio Arronte", "Modelo IA", "mindtrack_dataset_v1.csv")):
            if os.path.exists(cand):
                ruta_dataset = cand
                break
    if not (ruta_dataset and os.path.exists(ruta_dataset)):
        sys.exit("No encuentro mindtrack_dataset_v1.csv. Pasa --dataset RUTA.")

    ds = {r["ID"]: r for r in csv.DictReader(open(ruta_dataset, encoding="utf-8-sig"))}
    perfiles = [r for r in csv.DictReader(open(ruta_perfiles, encoding="utf-8-sig"))
                if r["estado_cuenta"] == "publica_con_posts"]
    primer_post = {}
    if os.path.exists(ruta_posts):
        for p in csv.DictReader(open(ruta_posts, encoding="utf-8-sig")):
            if p["es_del_perfil"] != "si":
                continue
            f = p["fecha"]
            if f and (p["id"] not in primer_post or f < primer_post[p["id"]]):
                primer_post[p["id"]] = f

    filas, aciertos_banda, errores = [], 0, []
    for r in perfiles:
        real = ds.get(r["id"], {}).get("edad", "")
        real = int(real) if str(real).isdigit() else None
        res = inferir(bio=r["biografia"], nombre=r["nombre"], usuario=r["usuario"],
                      fecha_primer_post=primer_post.get(r["id"]))
        filas.append((r["id"], real, res))
        if real and res["edad_estimada"] and res["confianza"] in ("alta", "media"):
            err = abs(res["edad_estimada"] - real)
            errores.append(err)
            if banda_de(res["edad_estimada"]) == banda_de(real):
                aciertos_banda += 1

    print("\nVALIDACION DE INFERENCIA DE EDAD  (n=%d perfiles con edad conocida)\n" % len(filas))
    print("%-10s %5s %5s %-8s %s" % ("ID", "real", "est", "confianza", "evidencia"))
    print("-" * 96)
    for pid, real, res in sorted(filas, key=lambda f: (f[2]["confianza"] == "nula", f[0])):
        print("%-10s %5s %5s %-8s %s" % (
            pid, real if real else "?",
            res["edad_estimada"] if res["edad_estimada"] else "-",
            res["confianza"],
            (res["evidencia"] or "; ".join(res["señales"]))[:60]))

    usables = [f for f in filas if f[2]["confianza"] in ("alta", "media")]
    con_baja = [f for f in filas if f[2]["confianza"] == "baja"]
    print("-" * 96)
    print("Cobertura confianza alta/media : %d/%d = %.0f%%" % (
        len(usables), len(filas), 100.0 * len(usables) / max(1, len(filas))))
    print("Cobertura si se acepta 'baja'  : %d/%d = %.0f%%" % (
        len(usables) + len(con_baja), len(filas),
        100.0 * (len(usables) + len(con_baja)) / max(1, len(filas))))
    if errores:
        print("Error absoluto medio           : %.1f años (n=%d)" % (
            sum(errores) / len(errores), len(errores)))
        print("Error maximo                   : %d años" % max(errores))
        print("Acierto de banda               : %d/%d" % (aciertos_banda, len(errores)))
        print("Dentro de +/-2 años            : %d/%d" % (
            sum(1 for e in errores if e <= 2), len(errores)))
    print("\nLectura: la inferencia de edad NO es un filtro suficiente por si sola.")
    print("Con esta cobertura hay que sembrar donde la edad ya este acotada por el")
    print("origen (cuentas de prepa, hashtags de generacion) y usar esto para")
    print("confirmar, no para descubrir.\n")
    return filas


def correr_sobre_global(ruta_global, salida="candidatos_edad.csv"):
    datos = json.load(open(ruta_global, encoding="utf-8"))
    resultados = datos.get("resultados", datos if isinstance(datos, list) else [])
    filas = []
    for r in resultados:
        posts = r.get("posts_data") or []
        fechas = sorted(p.get("fecha") for p in posts if p.get("fecha"))
        caps = [p.get("caption") or "" for p in posts][:40]
        res = inferir(bio=r.get("biografia", ""), nombre=r.get("nombre", ""),
                      usuario=r.get("usuario", ""), captions=caps,
                      fecha_primer_post=fechas[0] if fechas else None)
        filas.append({
            "id": r.get("id", ""), "usuario": r.get("usuario", ""),
            "estado_cuenta": r.get("estado_cuenta", ""),
            "edad_estimada": res["edad_estimada"] or "",
            "banda": res["banda"] or "", "confianza": res["confianza"],
            "evidencia": res["evidencia"], "conflicto": res["conflicto"],
            "admisible": "si" if en_rango_estudio(res) else "no",
        })
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    adm = sum(1 for x in filas if x["admisible"] == "si")
    print("%d perfiles -> %d admisibles (15-29, confianza alta/media). %s"
          % (len(filas), adm, salida))


if __name__ == "__main__":
    if "--validar" in sys.argv:
        i = sys.argv.index("--dataset") + 1 if "--dataset" in sys.argv else None
        validar(ruta_dataset=sys.argv[i] if i else None)
    elif "--global" in sys.argv:
        correr_sobre_global(sys.argv[sys.argv.index("--global") + 1])
    else:
        print(__doc__)


# EDAD EN CAPTIONS (etapa 3)
# Un caption es texto que la persona escribio sobre si misma en una fecha
# conocida. "cumplo 17" publicado en 2023 significa 20 hoy: la fecha del post
# manda. Solo se aceptan formulas en PRIMERA PERSONA: "19 años" a secas en un
# caption suele ser de otra persona o de un negocio (caso real: usuario_ejemplo10,
# "19 años se dicen facil", era el aniversario de su clinica).

_CAPTION_PATRONES = (
    # (regex, confianza)
    (r"\b(?:hoy\s+)?cumpl(?:o|[ií]|iendo)\s+(?:mis\s+)?([0-9]{2})\b", "alta"),
    (r"\b(?:ya\s+)?tengo\s+([0-9]{2})\s*(?:años|anios|anos)\b", "alta"),
    (r"\bmis\s+([0-9]{2})\s*(?:años|anios|anos|primaveras|añitos)\b", "alta"),
    (r"\b(?:celebrando|festejando|estrenando)\s+(?:mis\s+)?([0-9]{2})\b", "media"),
    (r"\ba\s+mis\s+([0-9]{2})\b", "media"),
    (r"\bmis\s+([0-9]{2})\b", "media"),
    (r"\bhappy\s+([0-9]{2})(?:st|nd|rd|th)?\s+(?:birthday|bday|b-day)\s+to\s+me\b", "alta"),
    (r"\bturn(?:ed|ing)\s+([0-9]{2})\b", "alta"),
    (r"\b([0-9]{2})\s*(?:años|anios)\s+de\s+(?:vida|existencia)\b", "media"),
)


def _normalizar_caption(texto):
    """Como _normalizar pero SIN borrar palabras con letras y digitos pegados:
    en un caption "20th" o "18vo" son parte de la frase, no un handle. Los
    handles en captions siempre llevan @, asi que basta con quitar esos."""
    t = "".join(SUPERINDICES.get(c, c) for c in (texto or ""))
    t = re.sub(r"@[\w.]+", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"#\w+", " ", t)
    return t


def señal_captions(captions_con_fecha):
    """captions_con_fecha: lista de (texto, fecha_iso_o_None).

    Devuelve (edad_hoy, confianza, evidencia) o (None, "nula", "").
    La edad se ajusta por la antiguedad del post. Si dos posts distintos dan
    edades coherentes (+/-1 tras ajustar) la confianza sube a alta."""
    hallazgos = []
    for texto, fecha in captions_con_fecha or []:
        if not isinstance(texto, str) or not texto.strip():
            continue
        t = _fechas_a_enmascarar(_normalizar_caption(texto)).lower()
        anio_post = None
        if fecha:
            try:
                anio_post = datetime.fromisoformat(str(fecha)[:19]).year
            except (ValueError, TypeError):
                anio_post = None
        for patron, conf in _CAPTION_PATRONES:
            m = re.search(patron, t, re.I)
            if not m:
                continue
            e = int(m.group(1))
            if not (EDAD_MIN - 3 <= e <= EDAD_MAX + 5):
                continue
            ajuste = (ANIO_ACTUAL - anio_post) if anio_post else 0
            hallazgos.append((e + ajuste, conf, "caption %s: %r" % (
                str(fecha)[:10] if fecha else "s/f", m.group(0))))
            break
    if not hallazgos:
        return None, "nula", ""
    orden = {"alta": 2, "media": 1}
    hallazgos.sort(key=lambda h: -orden.get(h[1], 0))
    edad, conf, ev = hallazgos[0]
    if len(hallazgos) > 1 and abs(hallazgos[1][0] - edad) <= 1:
        conf = "alta"
        ev += " + " + hallazgos[1][2]
    return edad, conf, ev
