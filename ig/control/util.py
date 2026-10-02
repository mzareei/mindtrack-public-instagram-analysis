# -*- coding: utf-8 -*-
"""
Utilidades compartidas del pipeline de control.

Dos cosas que se descubrieron con el piloto del 2 sep 2026 y que rompian todo
en silencio:

1. `followers` NO es un numero. El scraper lo guarda tal como lo escribe
   Instagram: "1,180", "158K", "25.2K", "83.4K". Compararlo con un limite
   numerico revienta o, peor, no revienta y deja pasar cualquier cosa.

2. Las biografias de cuentas profesionales llevan pegada la ETIQUETA DE
   CATEGORIA que pone Instagram: "Digital creator", "College & university",
   "Mexican Restaurant", "Fertility Doctor", "Photographer", "Athlete",
   "Politician". Esa etiqueta no la escribio la persona, la puso la plataforma,
   y es la mejor señal disponible de que la cuenta NO es de un particular.
   En el piloto, 12 de 25 perfiles publicos la traian.

   Excepcion importante: "Personal blog" es una categoria que eligen muchisimos
   adolescentes. Uno de los propios pacientes (MINDxxxx) la tiene. Esa NO
   descarta.
"""

import os
import re

# Categorias profesionales de Instagram observadas o esperables. La lista no
# tiene que ser exhaustiva: se detecta cualquier etiqueta al principio de la
# bio que coincida con estos patrones.
CATEGORIAS_PROFESIONALES = [
    r"digital creator", r"creador digital", r"public figure", r"figura publica",
    r"artist\b", r"musician", r"band\b", r"photographer", r"fotograf",
    r"athlete", r"atleta", r"coach", r"personal trainer",
    r"college & university", r"university", r"school", r"education",
    r"escuela", r"universidad", r"preparatoria",
    r"restaurant", r"food", r"cafe", r"bar\b", r"bakery",
    r"health/beauty", r"medical", r"doctor", r"clinic", r"dentist", r"hospital",
    r"product/service", r"shopping & retail", r"retail", r"local business",
    r"entrepreneur", r"business", r"company", r"brand\b", r"store", r"shop\b",
    r"politician", r"political", r"government", r"nonprofit", r"organization",
    r"media/news", r"news", r"magazine", r"publisher", r"broadcasting",
    r"community\b", r"gaming video creator", r"video creator",
    r"beauty, cosmetic", r"clothing", r"apparel", r"jewelry",
    r"real estate", r"travel", r"tour", r"event", r"venue",
    r"consulting", r"agency", r"software", r"app page",
]
# La unica categoria que NO descarta: la usan muchos adolescentes.
CATEGORIAS_PERMITIDAS = [r"personal blog", r"blog personal"]

_RE_CAT = re.compile("|".join(CATEGORIAS_PROFESIONALES), re.I)
_RE_CAT_OK = re.compile("|".join(CATEGORIAS_PERMITIDAS), re.I)


def numero(valor, defecto=0):
    """Convierte "1,180", "158K", "25.2K", "1.2M" o 1180 a int.

    Devuelve `defecto` si no se puede leer. NUNCA devuelve una cadena, que es
    justo lo que rompia las comparaciones con los limites de la envolvente.
    """
    if valor is None:
        return defecto
    if isinstance(valor, (int, float)):
        return int(valor)
    t = str(valor).strip().replace(",", "").replace(" ", "")
    if not t:
        return defecto
    mult = 1
    if t[-1:].upper() == "K":
        mult, t = 1000, t[:-1]
    elif t[-1:].upper() == "M":
        mult, t = 1000000, t[:-1]
    try:
        return int(float(t) * mult)
    except ValueError:
        return defecto


def categoria_profesional(biografia):
    """Si la bio empieza con una etiqueta de categoria de Instagram, la
    devuelve. Si no, devuelve "".

    Solo mira el principio de la bio (primera linea, primeros ~40 caracteres):
    la etiqueta va siempre ahi. Buscarla en toda la bio daria falsos positivos
    con cualquiera que mencione "artist" en una frase.
    """
    if not biografia:
        return ""
    cabeza = str(biografia).split("\n")[0][:45]
    if _RE_CAT_OK.search(cabeza):
        return ""
    # La etiqueta va al principio, pero puede llevar un calificador delante:
    # "Mexican Restaurant", "Fertility Doctor", "Gaming Video Creator". Anclar
    # en la posicion 0 dejaba pasar esas.
    # El discriminante es que la etiqueta la escribe Instagram en Title Case,
    # asi que la palabra de categoria va en mayuscula. Eso descarta el falso
    # positivo de "las luces tenues del bar existen para...", donde "bar" va en
    # minuscula dentro de una frase.
    for m in _RE_CAT.finditer(cabeza):
        texto = m.group(0)
        if texto[:1].isupper():
            return texto
    return ""


def es_cuenta_personal(perfil):
    """True si el perfil parece de un particular y no de una marca o institucion."""
    return not categoria_profesional(perfil.get("biografia", ""))


# ORGANIZACIONES SIN ETIQUETA DE CATEGORIA
# Lo que enseño la corrida del 3-4 sep 2026: las instituciones etiquetan a
# OTRAS instituciones. La FEU etiqueta a sus capitulos (usuario_ejemplo21, xpresion.ing),
# el SEMS a sus prepas, el CUCS a sus oficinas. Muchas de esas cuentas no
# llevan la etiqueta de categoria de Instagram, asi que hay que reconocerlas
# por como hablan (primera persona del plural, "cuenta oficial") y por como se
# llaman.
import re as _re

_ORG_BIO_FUERTE = _re.compile(
    r"(\bsomos\b|\bnosotr[oa]s\b|\bnuestr[oa]s?\s+(?:alumn|estudiant|comunidad|equipo|escuela|plantel|centro|socios)"
    r"|cuenta\s+oficial|p[aá]gina\s+oficial|perfil\s+oficial|canal\s+oficial"
    r"|representaci[oó]n|sociedad\s+de\s+alumnos|comit[eé]\b|\bconsejo\b|colectivo|\btaller\b"
    r"|\biniciativa\b|\boficina\b|control\s+escolar|\btrabajamos\b|\bofrecemos\b|\bbrindamos\b"
    r"|bienvenid[oa]s\s+a|\bclub\b|grupo\s+(?:estudiantil|de|cultural|juvenil|musical)"
    r"|\bnoticias\b|informaci[oó]n\s+(?:sobre|de|acerca)|s[ií]guenos|cont[aá]ctanos|escr[ií]benos"
    r"|inscripciones|convocatoria|\bfestival\b|red\s+de\b|programa\s+de\b|proyecto\s+de\b"
    r"|\bmovimiento\b|asociaci[oó]n|fundaci[oó]n|organizaci[oó]n|\ba\.c\.|\bs\.a\.|\bong\b"
    r"|\bequipo\s+(?:de|representativo)|selecci[oó]n\s+de|\bmemes?\b|\bhumor\b|\bconfesiones\b"
    r"|\bspotted\b|\bcrush\b|espacio\s+(?:donde|para|de)|vinculaci[oó]n|\balianzas?\b)", _re.I)

# Palabras de LUGAR que usa tanto una institucion como un alumno que dice donde
# estudia. Solo descartan si no hay señal de persona (edad, "estudiante",
# titulo propio, primera persona del singular).
_ORG_BIO_DEBIL = _re.compile(r"(bachillerato|preparatoria\b|\bescuela\b|\buniversidad\b|centro\s+(?:universitario|educativo))", _re.I)
_PERSONA = _re.compile(r"(estudiante|alumn[oa]|egresad[oa]|estudi[oa]\b|estudiando|\blic\.|\bing\.|\btec\.|\bsoy\b|\bmi\b|\byo\b|\bme\b|(?<![0-9])[0-9]{2}(?![0-9]))", _re.I)

_ORG_HANDLE = _re.compile(
    r"(xpresion|axo[._]|consejo|taller|grafica|control|atencion|alianzas|vision|leones_|geotech"
    r"|voces_|teatro|zith|nightlife|\bclub|billar|oficial|comite|sociedad|colectivo|iniciativa"
    r"|proyecto|programa|red_|_red\b|fest\b|eventos|noticias|revista|grupo|equipo|banda|ensamble"
    r"|coro_|orquesta|ballet|danza|deportes|futbol|basquet|volley|team|squad|crew|studio|estudio"
    r"|escuela|academia|instituto|centro|universidad|facultad|division|coordinacion|direccion"
    r"|secretaria|departamento|laboratorio|lab_|_lab\b|momazos|memes|confesiones|spotted"
    r"|prepa|bachillerato|sems|cucs|cucei|cucea|cutonala|\bcut_|_cut\b|udg|udeg|jalisco|gdl_|_gdl)", _re.I)

# GEOGRAFIA. Los pacientes son de Jalisco (hospital de Zapopan). Un control de
# Chilpancingo o Monterrey no es comparable. Se descarta si la bio nombra otro
# estado o ciudad y NO nombra nada de Jalisco.
_JALISCO = _re.compile(r"(\bgdl\b|guadalajara|zapopan|jalisco|\bjal\b|tlaquepaque|tonal[aá]|tlajomulco|tequila"
                       r"|chapala|ocotl[aá]n|lagos de moreno|guzm[aá]n|vallarta|ameca|arandas|tepatitl[aá]n"
                       r"|autl[aá]n|colotl[aá]n|zmg|tapat[ií])", _re.I)
_FUERA_JALISCO = _re.compile(r"(\bcdmx\b|ciudad de m[eé]xico|monterrey|\bmty\b|\bpuebla\b|quer[eé]taro|\bqro\b"
                             r"|chilpan|acapulco|guerrero|oaxaca|chiapas|tijuana|mexicali|hermosillo|culiac[aá]n"
                             r"|sinaloa|\ble[oó]n\b|guanajuato|\bgto\b|aguascalientes|\bags\b|morelia|michoac[aá]n"
                             r"|\bcolima\b|nayarit|\btepic\b|veracruz|m[eé]rida|canc[uú]n|chihuahua|torre[oó]n"
                             r"|saltillo|san luis potos[ií]|\bslp\b|toluca|edomex|cuernavaca|durango|zacatecas"
                             r"|tabasco|campeche|tamaulipas|sonora|\bbcs\b|la paz\b)", _re.I)


def fuera_de_jalisco(biografia):
    b = biografia or ""
    m = _FUERA_JALISCO.search(b)
    if m and not _JALISCO.search(b):
        return m.group(0)
    return ""


def es_organizacion(biografia, usuario=""):
    """Devuelve el motivo si la cuenta parece de una organizacion, "" si no."""
    b = biografia or ""
    m = _ORG_BIO_FUERTE.search(b)
    if m:
        return "bio de organizacion (%s)" % m.group(0).strip()
    m = _ORG_HANDLE.search(usuario or "")
    if m:
        return "handle de organizacion (%s)" % m.group(0)
    m = _ORG_BIO_DEBIL.search(b)
    if m and not _PERSONA.search(b):
        return "bio de lugar sin señal de persona (%s)" % m.group(0).strip()
    return ""


# ID ESTABLE DE CONTROL
# El bug del 05/09/2026: los ids se asignaban por POSICION en la lista
# ("CTRL%04d" % n). Cada vez que la lista de aprobados se reescribia (un ciclo
# nuevo, un reevaluar) todo el mundo se corria una fila, asi que CTRLxxxx era
# hoy una persona y mañana otra. Y como `scrappingData_ig.py --reanudar` salta
# por ID, no por usuario, se saltaron 33 controles aprobados que nunca se
# llegaron a extraer: su id posicional ya estaba en el checkpoint, con otra
# persona detras.
#
# Ahora el id sale del handle, asi que es el mismo para siempre: se puede
# reanudar, cruzar ficheros por id y volver a generar la lista sin que nada
# se mueva.
import hashlib as _hashlib


def id_control(usuario, prefijo="CTRL"):
    h = _hashlib.sha1((usuario or "").strip().lower().encode("utf-8")).hexdigest()[:6].upper()
    return "%s%s" % (prefijo, h)


def ruta_dataset(nombre="mindtrack_dataset_v1.csv"):
    """Localiza el dataset clinico sin depender de donde este montado nada.

    Hasta el 9/9/2026 los scripts buscaban `RAIZ/../Rio Arronte/Modelo IA/`,
    que solo existia por casualidad del montaje remoto ($HOME/mnt/Mindtrack y
    $HOME/mnt/Rio Arronte, uno al lado del otro). En Windows eso es
    C:\\Github\\Rio Arronte, que no existe: la carpeta real vive en OneDrive.
    Sin el dataset, `emparejar.py` no sabe la edad de ningun caso y no empareja
    a nadie, en silencio.

    Orden de busqueda:
      1. variable MINDTRACK_DATASET (ruta completa), tambien desde .env
      2. RAIZ/<nombre>
      3. RAIZ/../Rio Arronte/Modelo IA/<nombre>
      4. ~/OneDrive*/0-Projects/Rio Arronte/Modelo IA/<nombre>
    """
    import glob as _glob
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = os.environ.get("MINDTRACK_DATASET")
    if not env:
        dotenv = os.path.join(raiz, ".env")
        if os.path.exists(dotenv):
            for l in open(dotenv, encoding="utf-8"):
                if l.strip().startswith("MINDTRACK_DATASET="):
                    env = l.split("=", 1)[1].strip().strip('"').strip("'")
    candidatos = [env] if env else []
    candidatos += [
        os.path.join(raiz, nombre),
        os.path.join(raiz, "..", "Rio Arronte", "Modelo IA", nombre),
    ]
    home = os.path.expanduser("~")
    candidatos += _glob.glob(os.path.join(home, "OneDrive*", "0-Projects", "Rio Arronte", "Modelo IA", nombre))
    for c in candidatos:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None


# CUENTAS QUE NO SON UNA PERSONA, aunque la bio no lo diga
# Lo que enseño la re-extraccion del 9/9/2026: la evidencia institucional deja
# entrar cuentas que una escuela etiqueta y que no son alumnos: una banda
# ("The Chevys p22"), un laboratorio ("a.t.e.lab"), un movimiento estudiantil
# ("con._accion"), un posgrado ("Maestria en Ciencias en Quimica"), una marca
# de licor ("Hijos de Maria Morales Shot") y una uroginecologa en ejercicio a
# la que el inferidor puso 21 años. `es_organizacion` mira solo la bio y
# ninguna de esas bios lleva los marcadores fuertes. Aqui se mira tambien el
# NOMBRE (donde va el "DRA") y frases de producto, colectivo o programa.
_TITULO_EN_NOMBRE = _re.compile(
    r"^\s*(dr|dra|lic|mtro|mtra|ing|arq|psic|c\.?p|md|phd)\b\.?\s", _re.I)
_NO_PERSONA = _re.compile(
    r"\b(maestr[ií]a en|doctorado en|licenciatura en|posgrado|laboratorio|\blab\b|expo\b|"
    r"colectivo|movimiento|asociaci[oó]n|sociedad de|consejo|uni[oó]n estudiantil|"
    r"federaci[oó]n|coordinaci[oó]n|departamento de|facultad de|"
    r"disfr[uú]talo|tu nuevo .{0,20}favorito|env[ií]os|pedidos|cotiza|men[uú]\b|"
    r"sucursal|horario|booking|contrataciones|puro ritmo|damos voz|punto de encuentro)", _re.I)
_ESPECIALIDAD = _re.compile(
    r"\b(ginecolog|urolog|cardiolog|pediatr|dermatolog|psiquiatr|odont|"
    r"cirujan|anestesi|traumat|oftalm|neur[oó]log|nefr[oó]log|internista)", _re.I)


def es_no_persona(nombre, biografia, posts=None, usuario=""):
    """Motivo si la cuenta no es de una persona particular, "" si lo es.

    `posts` es opcional: la lista de posts extraidos. Si mas de la mitad son
    de OTRAS cuentas (colaboraciones/etiquetas) y hay menos de 5 propios, la
    cuenta es un repetidor, no un autor.
    """
    n = (nombre or "").strip()
    b = (biografia or "").replace("\n", " ")
    u = (usuario or "").lower()
    if _re.search(r"(^|[._])lab([._]|$)|laboratorio|oficial$|official$|_mx$|\.mx$", u):
        return "handle de organizacion (%s)" % u
    m = _TITULO_EN_NOMBRE.search(n)
    if m:
        return "titulo profesional en el nombre (%s)" % m.group(1)
    m = _NO_PERSONA.search(n)
    if m:
        return "nombre de organizacion o programa (%s)" % m.group(0)
    m = _NO_PERSONA.search(b)
    if m:
        return "bio de organizacion, producto o programa (%s)" % m.group(0)
    m = _ESPECIALIDAD.search(n + " " + b)
    if m:
        return "especialidad medica en ejercicio (%s)" % m.group(0)
    if posts:
        propios = sum(1 for x in posts if x.get("es_del_perfil") in (True, "si", "True"))
        ajenos = len(posts) - propios
        if propios < 5 and ajenos > propios:
            return "repetidor: %d posts propios frente a %d ajenos" % (propios, ajenos)
    return ""
