import re, csv, json, sys, time, os
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Carga las variables de un archivo .env en la raiz del proyecto, si existe.
# python-dotenv es opcional: sin el, las credenciales se leen igual desde las
# variables de entorno reales del sistema.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# CONFIG
# Credenciales de Instagram. NUNCA escribirlas aqui: se leen del archivo .env
# (que esta en .gitignore) o de las variables de entorno. Ver .env.example.
IG_USUARIO = os.environ.get("IG_USUARIO")
IG_PASSWORD = os.environ.get("IG_PASSWORD")

CSV_PATH, RESULTADOS_DIR = "formato(Sheet1).csv", "resultados_ig"
MAX_INTENTOS_SIN_CAMBIO, ESPERA_LOGIN, ESPERA_CAPTION = 3, 15, 4
# Mientras no se resuelva del todo la extracción de respuestas: guarda en
# resultados_ig/debug_dom/ el HTML de cada post YA con las respuestas
# expandidas, para poder diagnosticar contra el DOM real de Instagram
# (los selectores no se pueden validar a ciegas sin verlo). Poner en False
# una vez que las respuestas salgan bien y ya no se necesite depurar.
DEBUG_GUARDAR_DOM = True

# Defecto 1: tope de seguridad de vueltas de scroll, para que un perfil enorme
# o un scroll infinito que no termina nunca no deje colgada la corrida.
MAX_SCROLLS = 400

# Defecto 4 (urgente): las URLs del CDN de Instagram caducan (token `oe=`).
# La corrida del 27/08/2026 no bajo ningun binario y sus URLs vencian el
# 1 de septiembre. Con esto el archivo se guarda en el momento, junto al JSON.
# Defecto 5: la rejilla del perfil tambien lista posts de OTRAS cuentas
# (colaboraciones y publicaciones donde etiquetaron al paciente). En la corrida
# del 27/08/2026 se colaron 22 de 519 posts, 20 de ellos en un solo perfil
# (usuario_ejemplo4: 20 reels de quepasaguadalajara sobre 31 posts). Eso metia
# texto y 140 comentarios que no son del paciente dentro de su corpus.
# Ahora cada post queda marcado con `autor_post` y `es_del_perfil`. Con
# EXCLUIR_POSTS_AJENOS = True ni siquiera se visitan.
EXCLUIR_POSTS_AJENOS = False

DESCARGAR_MEDIA = True
MEDIA_SUBDIR = "media"
# Cuanto esperar a que el navegador registre la descarga del mp4 tras darle play.
ESPERA_VIDEO, ESPERA_VIDEO_INTENTOS = 1.5, 3

# Cuantos perfiles seguidos pueden salir "tiene posts pero no coseche ninguno"
# antes de cortar la corrida. Es el sintoma de que Instagram empezo a limitar:
# sin esto, una corrida larga sigue horas llenando el dataset de vacios y no se
# nota hasta el final.
LIMITE_ANOMALIAS = 3
UA_DESCARGA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# UTILIDADES
def save_json(data, filename):
    os.makedirs(RESULTADOS_DIR, exist_ok=True)
    ruta = os.path.join(RESULTADOS_DIR, f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Guardado: {ruta}")
    return ruta

def save_json_en(data, ruta):
    """
    Guarda en una ruta FIJA (sin timestamp), de forma atomica: escribe un .tmp
    y luego lo renombra. Se usa para el checkpoint, que se reescribe una vez por
    perfil; si la corrida muere a media escritura, el archivo bueno sigue ahi.
    """
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)
    return ruta


def _serializable(d):
    """
    El item que sale del CSV trae objetos datetime en f_inicio / f_fin.
    procesar_perfil() los convierte a texto, pero la rama de error no lo hacia:
    si un solo perfil fallaba, esos datetime llegaban crudos al json.dump final
    y reventaba el guardado de TODA la corrida. Se normalizan aqui.
    """
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()}


def limpiar_nombre_archivo(t):
    return re.sub(r'[\\/*?:"<>|\s]', "_", str(t).strip()) if t else "sin_nombre"

def _walk_json(obj):
    """
    Recorre recursivamente cualquier estructura JSON (dict/list) y devuelve
    cada dict encontrado, sin importar la profundidad ni el orden de las
    claves internas. Usado para leer los datos de IG embebidos en <script
    type="application/json">, que son JSON válido pero con estructura y
    orden de campos que varía entre posts.
    """
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_json(v)


def _extraer_shortcode(url):
    m = re.search(r"/(?:p|reel)/([^/?]+)", url or "")
    return m.group(1) if m else None


def obtener_fecha_post(driver, url_post=None):
    """
    Extrae la fecha real de publicación leyendo el campo 'taken_at'
    (timestamp Unix) del JSON embebido en <script type="application/json">.
    NO se usa el <time> del DOM como fuente principal: la página tiene un
    <time> por cada comentario visible, y el primero en orden de documento
    no siempre es el del post — eso hacía que a veces se tomara la fecha de
    un comentario en vez de la del post, descuadrando el orden final.
    """
    shortcode = _extraer_shortcode(url_post)
    try:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        candidatos = []
        for script in soup.find_all("script", attrs={"type": "application/json"}):
            try:
                data = json.loads(script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for nodo in _walk_json(data):
                ta = nodo.get("taken_at")
                code = nodo.get("code")
                if isinstance(ta, (int, float)) and isinstance(code, str):
                    candidatos.append((code, ta))
        if candidatos:
            if shortcode:
                for code, ta in candidatos:
                    if code == shortcode:
                        return datetime.fromtimestamp(ta)
            # Si no hay match exacto de shortcode, usar el primero encontrado
            return datetime.fromtimestamp(candidatos[0][1])
    except Exception:
        pass

    # Fallback: <time> restringido al header del article (evita <time> de comentarios)
    try:
        t = driver.find_element(By.XPATH, "//article//header//time | //article//a[time]/time")
        dt = t.get_attribute("datetime") or ""
        if dt and len(dt) >= 10:
            return datetime.fromisoformat(dt.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    return None

def _sustituir_usuario(texto, usuario_real, etiqueta):
    """Cambia el usuario real por la etiqueta del paciente, respetando limites de token."""
    if not texto or not usuario_real:
        return texto
    return re.sub(r"(?<![\w.])%s(?![\w.])" % re.escape(usuario_real),
                  etiqueta, texto, flags=re.I)


def _anonimizar_menciones(texto, anon_de, usuario_real, etiqueta_paciente):
    """Las menciones @handle pasan por el MISMO mapa que los comentaristas, asi
    que si alguien comenta y ademas es mencionado recibe la misma etiqueta."""
    if not texto:
        return texto

    def _repl(m):
        h = m.group(1)
        if usuario_real and h.lower() == usuario_real.lower():
            return "@" + etiqueta_paciente
        return "@[%s]" % anon_de(h)

    return re.sub(r"@([A-Za-z0-9._]{2,30})", _repl, texto)


def _patron_handles_conocidos(handles):
    """Regex que casa CUALQUIER handle de la corrida, con o sin @, con o sin #.

    Por que hace falta. Hasta el 05/09/2026 solo se sustituian (a) el usuario
    del propio perfil y (b) las menciones con @. Se colaban dos formas:

      - handles SUELTOS dentro del texto de un comentario. El DOM de Instagram
        mete su propia interfaz en ese texto ("usuario_ejemplo3
        cutonala_vision_ingenierias xpresion.ing CTRLxxxx and 3 others More
        options"), y ahi los handles van sin arroba.
      - handles dentro de un HASHTAG (#xpresioncut). Los hashtags se conservan
        a proposito, pero uno que ES un handle reidentifica igual.

    Con la lista de usuarios de la corrida se sustituyen todos, vengan como
    vengan. Se ordenan por longitud descendente para que un handle que sea
    prefijo de otro no lo parta a medias.
    """
    conocidos = sorted({(h or "").strip().lower() for h in (handles or [])
                        if h and len(str(h).strip()) >= 4}, key=len, reverse=True)
    if not conocidos:
        return None
    return re.compile(r"(?<![A-Za-z0-9._])(" + "|".join(re.escape(h) for h in conocidos) +
                      r")(?![A-Za-z0-9._])", re.I)


def construir_resultado_anonimo(res, handles_corrida=None):
    """
    Anonimiza comentarios manteniendo jerarquia (comment_id/parent_comment_id).
    El mapa de autor->anonimo es GLOBAL para todo el perfil (todos sus posts),
    asi que si la misma persona comenta en varios posts, recibe la misma
    etiqueta "Anonimo N" en todos ellos.

    DEFECTO 2 CORREGIDO (28/08/2026). La version anterior quitaba `usuario`,
    `nombre` y `profile_pic` y renombraba a los comentaristas, pero dejaba el
    usuario del paciente DOS veces dentro de cada post: en `url` y dentro de
    `caption_raw` ("44 likes, 2 comments - usuario_ejemplo19 on July 20, 2026: ...").
    En la corrida del 27/08/2026 eso ocurria en 519 de 519 posts, es decir que
    el archivo "anonimo" reidentificaba al paciente de inmediato y ademas
    llevaba a su perfil. Con el folio de etica P000850 encima, ese archivo no
    debia salir de la maquina.

    Ahora:
      - el usuario real se sustituye por el ID del paciente en url, caption y
        caption_raw;
      - las menciones @handle de captions y comentarios pasan por el mismo
        mapa de anonimato;
      - la biografia NO se copia al export anonimo (suele traer nombre real,
        ciudad o centro de trabajo);
      - el shortcode del post SI se conserva, a proposito, para poder volver
        al material original durante la anotacion.

    La red de seguridad esta en verificar_anonimato(), que se corre en main().
    """
    pid = str(res.get("id") or "SIN_ID")
    usuario_real = (res.get("usuario") or res.get("username") or "").strip()
    patron_conocidos = _patron_handles_conocidos(handles_corrida)

    mapa_anonimos = {}
    contador_anon = [1]

    def anon_de(autor_real):
        clave = (autor_real or "").strip().lower() or "_desconocido"
        if clave not in mapa_anonimos:
            mapa_anonimos[clave] = "Anonimo %d" % contador_anon[0]
            contador_anon[0] += 1
        return mapa_anonimos[clave]

    def etiqueta_de(handle):
        """Etiqueta apta para una URL: el ID del paciente, o Anonimo_N."""
        if usuario_real and (handle or "").lower() == usuario_real.lower():
            return pid
        return anon_de(handle).replace(" ", "_")

    def _reescribir_urls(txt):
        """
        Cambia el dueno de CUALQUIER url de post de Instagram que aparezca en el
        texto, no solo la del paciente. Hace falta por el defecto 5: la rejilla
        traia posts de otras cuentas, y sus URLs nombraban a esas cuentas dentro
        del archivo "anonimo".
        """
        return re.sub(
            r"(https?://www\.instagram\.com/)([A-Za-z0-9_.]+)(/(?:p|reel)/)",
            lambda m: m.group(1) + etiqueta_de(m.group(2)) + m.group(3),
            txt)

    def _reescribir_autoria_caption(txt):
        """
        caption_raw viene con el formato de meta-descripcion de Instagram:
        "44 likes, 2 comments - <usuario> on July 20, 2026: ...". Ese <usuario>
        NO siempre es el paciente: en los posts ajenos del defecto 5 es la otra
        cuenta. Se etiqueta aqui, antes que nada, para no dejarlo pasar.
        """
        # El handle puede ir despues de "- " (caption_raw completo) o al
        # PRINCIPIO del campo (username_post, que es esa misma cola recortada).
        # Solo se contemplaba la primera forma, asi que en la corrida del
        # 05/09/2026 se colaron 11 handles reales, xpresioncut 14 veces.
        # Ademas la fecha puede venir en ingles ("on March 5, 2026") o en
        # espanol ("el 5 de marzo de 2026").
        return re.sub(
            r"(^|-\s+)([A-Za-z0-9._]{2,30})(\s+(?:on|el)\s+)",
            lambda m: m.group(1) + (m.group(2) if re.match(r"^(MIND\d+|CTRL\d+|PILO\d+|PEND\d+|Anonimo_\d+)$", m.group(2))
                                    else etiqueta_de(m.group(2))) + m.group(3),
            txt)

    def limpiar(txt):
        if not txt:
            return txt
        txt = _reescribir_autoria_caption(txt)
        txt = _reescribir_urls(txt)
        txt = _sustituir_usuario(txt, usuario_real, pid)
        txt = _anonimizar_menciones(txt, anon_de, usuario_real, pid)
        # Ultima pasada: cualquier handle de la corrida que haya llegado hasta
        # aqui suelto o dentro de un hashtag.
        if patron_conocidos:
            txt = patron_conocidos.sub(lambda m: etiqueta_de(m.group(1)), txt)
        return txt

    # Antes esto era una lista escrita a mano de campos a limpiar, y fallo justo
    # como fallan las listas escritas a mano: al anadir la descarga de media
    # aparecieron `media_local` y `video_local` con la forma
    # "media/<usuario>/<shortcode>.jpg", nadie los agrego a la lista, y el
    # export de la corrida del 28/08/2026 salio con 30 usuarios reales dentro.
    # Ahora se limpia CUALQUIER valor de texto del post, asi que un campo nuevo
    # queda cubierto solo. Los campos que no contienen nombres (fechas, ids) no
    # se ven afectados porque la sustitucion no encuentra nada que cambiar.
    NO_LIMPIAR = ("fecha_post_iso",)

    posts_anonimizados = []
    for p in res.get("posts_data", []):
        comentarios_anonimos = []

        for cmt in (p.get("comments") or []):
            # Compatibilidad: si por algun motivo llega un string suelto
            # (formato viejo), lo dejamos pasar pero ya anonimizado.
            if isinstance(cmt, str):
                comentarios_anonimos.append(limpiar(cmt))
                continue

            autor = (cmt.get("autor") or "").strip()
            comentarios_anonimos.append({
                "comment_id":        cmt.get("comment_id"),
                "es_reply":          cmt.get("es_reply", False),
                "parent_comment_id": cmt.get("parent_comment_id", ""),
                "autor_anonimo":     anon_de(autor),
                "es_del_paciente":   bool(usuario_real) and autor.lower() == usuario_real.lower(),
                "texto":             limpiar(cmt.get("texto")),
            })

        p_anon = dict(p)
        p_anon["comments"] = comentarios_anonimos
        # El autor del post se etiqueta igual que cualquier otra persona.
        if p_anon.get("autor_post"):
            p_anon["autor_post"] = etiqueta_de(p_anon["autor_post"])
        # username_post tambien es un campo de autor: se etiqueta directamente
        # en vez de confiar en que las regex de texto lo pillen. Si viene
        # corrupto (con la cola del caption pegada), se etiqueta el handle
        # inicial y el resto pasa por limpiar().
        if p_anon.get("username_post"):
            up = str(p_anon["username_post"]).strip()
            m_up = re.match(r"^@?([A-Za-z0-9._]{2,30})\b", up)
            if m_up and not re.match(r"^(MIND\d+|CTRL\d+|PILO\d+|PEND\d+|Anonimo_\d+)$", m_up.group(1)):
                up = etiqueta_de(m_up.group(1)) + up[m_up.end():]
            p_anon["username_post"] = limpiar(up)
        for campo, valor in list(p_anon.items()):
            if campo in NO_LIMPIAR or campo in ("comments", "autor_post", "username_post"):
                continue
            if isinstance(valor, str) and valor:
                p_anon[campo] = limpiar(valor)
        posts_anonimizados.append(p_anon)

    return {
        "id":               res.get("id"),
        "paciente":         pid,
        "followers":        res.get("followers"),
        "following":        res.get("following"),
        "posts":            res.get("posts"),
        "metricas_fuente":  res.get("metricas_fuente"),
        "estado_cuenta":    res.get("estado_cuenta"),
        "rango_fechas":     res.get("rango_fechas"),
        "posts_data":       posts_anonimizados,
        **({"error": res["error"]} if "error" in res else {})
    }


def verificar_anonimato(resultados_anonimos, resultados_reales):
    """
    Red de seguridad del defecto 2: busca cada usuario real dentro del JSON
    anonimo ya serializado. Si algo sobrevive lo dice fuerte, en vez de dejar
    que el archivo salga creyendo que esta limpio.
    Devuelve la lista de fugas [(usuario, apariciones), ...].
    """
    usuarios = sorted(
        {(r.get("usuario") or r.get("username") or "").strip() for r in resultados_reales} - {""},
        key=len, reverse=True)
    texto = json.dumps(resultados_anonimos, ensure_ascii=False)

    fugas = []
    for u in usuarios:
        n = len(re.findall(r"(?<![\w.])%s(?![\w.])" % re.escape(u), texto, flags=re.I))
        if n:
            fugas.append((u, n))

    if fugas:
        print("\n*** ALERTA: el JSON anonimo todavia contiene usuarios reales ***")
        for u, n in fugas:
            print("      %-28s %d apariciones" % (u, n))
        print("    NO compartas ese archivo hasta corregirlo.\n")
    else:
        print("Anonimato verificado: 0 apariciones de %d usuarios reales en el JSON anonimo."
              % len(usuarios))
    return fugas


# LOGIN / CSV
def iniciar_sesion(driver, wait):
    if not IG_USUARIO or not IG_PASSWORD:
        raise RuntimeError(
            "Faltan credenciales: define IG_USUARIO e IG_PASSWORD en un archivo "
            ".env en la raiz del proyecto (copia .env.example) o como variables "
            "de entorno del sistema."
        )
    driver.get("https://www.instagram.com/accounts/login/")
    # RESTAURADO: Nombres originales de los campos
    wait.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(IG_USUARIO)
    pw = wait.until(EC.presence_of_element_located((By.NAME, "pass")))
    pw.send_keys(IG_PASSWORD + Keys.RETURN)
    time.sleep(5)
    try: wait.until(EC.element_to_be_clickable((By.XPATH, "//*[text()='Ahora no']"))).click()
    except: pass

def limpiar_usuario(v):
    if not v: return None
    v = re.sub(r'https?://(www\.)?instagram\.com/|@', '', str(v).strip()).strip('/')
    return v if v else None

# Formatos aceptados en las columnas "F. Inicio" / "F. Fin", en orden de
# intento. El CSV que exporta Google Sheets usa M/D/AAAA (p. ej. "8/27/2026"),
# por eso el formato de mes primero va antes que el de dia primero.
# OJO: una fecha como "3/4/2026" es ambigua y se leera como 4 de marzo
# (mes primero). Si tus datos vienen en formato dd/mm/aaaa, mueve
# "%d/%m/%Y" al principio de esta lista.
FORMATOS_FECHA = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")

def parsear_fecha(valor):
    """Convierte el texto de una celda de fecha a datetime probando los
    formatos de FORMATOS_FECHA. Lanza ValueError si ninguno coincide."""
    texto = (valor or "").strip()
    if not texto:
        raise ValueError("celda de fecha vacia")
    for fmt in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    raise ValueError(f"formato no reconocido: {texto!r}")

def cargar_usuarios(ruta):
    usuarios = []
    with open(ruta, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            u = limpiar_usuario(r.get("instagram"))
            if not u: continue

            try:
                f_i = parsear_fecha(r.get("F. Inicio"))
                f_f = parsear_fecha(r.get("F. Fin")).replace(hour=23, minute=59, second=59)
            except ValueError as e:
                print(f"Error en formato de fecha para usuario {u}: {e}")
                continue

            usuarios.append({
                "id": r.get("id"),
                "usuario": u,
                "url": f"https://www.instagram.com/{u}/",
                "f_inicio": f_i,
                "f_fin": f_f
            })
    return usuarios

# SCRAPING LOGIC
_JS_LINKS_POSTS = (
    "return Array.from(document.querySelectorAll(\"a[href*='/p/'], a[href*='/reel/']\"))"
    "            .map(function(a){ return a.href.split('?')[0]; });"
)


def _dueno_de_url(u):
    """Devuelve el usuario dueno del post segun la URL, o "" si la URL no lo dice."""
    m = re.match(r"https?://www\.instagram\.com/([^/]+)/(?:p|reel)/", u or "")
    d = (m.group(1).lower() if m else "")
    return "" if d in ("p", "reel") else d


def _normalizar_link(h):
    """Normaliza un href a URL absoluta de post/reel, o None si no lo es."""
    if not h:
        return None
    h = h.split("?")[0]
    if h.startswith("/"):
        h = "https://www.instagram.com" + h
    return h if ("/p/" in h or "/reel/" in h) else None


def _posts_declarados(driver):
    """Cuantas publicaciones dice tener el perfil, leido de og:description
    ("1,234 Followers, 567 Following, 89 Posts - ..."). Sirve como OBJETIVO del
    scroll. El valor puede venir de cache y no ser exacto; da igual, aqui solo
    se usa para decidir si merece la pena seguir bajando."""
    try:
        desc = driver.find_element(
            By.XPATH, "//meta[@property='og:description']").get_attribute("content") or ""
    except Exception:
        return None
    m = re.search(r"([\d.,]+)\s*(?:Posts|posts|Publicaciones|publicaciones)", desc)
    if not m:
        return None
    try:
        return int(re.sub(r"[.,]", "", m.group(1)))
    except ValueError:
        return None


def hacer_scroll(driver):
    """
    Baja por el grid del perfil COSECHANDO los enlaces en cada paso.

    DEFECTO 1 CORREGIDO (28/08/2026). El grid de Instagram es una lista
    virtualizada: conforme se baja, las filas que salen de pantalla se
    DESMONTAN del DOM. La version anterior hacia todo el scroll y hasta el
    final leia driver.page_source una sola vez, asi que solo veia las ultimas
    filas renderizadas.

    Efecto medido en la corrida del 27/08/2026:
      - tope duro de 33 posts por perfil sin importar el tamano de la cuenta;
      - los perfiles con 33 posts o menos si daban 100%, porque ahi no hay
        virtualizacion que ejecutar;
      - el tramo capturado ademas era viejo (usuario_ejemplo13: 330 publicaciones,
        33 capturadas, todas de 2014-2015; usuario_ejemplo16: 250 publicaciones, 31
        capturadas, todas de jul-sep 2022);
      - cobertura global 519 de 1,530 = 33.9%.

    Ahora se cosecha en cada iteracion con una sola llamada de JS (barato, sin
    reparsear el HTML) y se acumula en un dict que preserva el orden de
    aparicion. Devuelve la lista de enlaces sin duplicados.
    """
    vistos = {}

    def cosechar():
        try:
            encontrados = driver.execute_script(_JS_LINKS_POSTS) or []
        except Exception:
            encontrados = []
        for h in encontrados:
            u = _normalizar_link(h)
            if u:
                vistos.setdefault(u, None)

    # DEFECTO 8 CORREGIDO (07/09/2026). La condicion de parada era solo "la
    # altura de la pagina no ha cambiado en 3 vueltas". Cuando Instagram tarda
    # en añadir la siguiente tanda (throttling, red lenta), 3 x 2.5 s no basta y
    # el scroll se daba por terminado con la primera pantalla del grid.
    # Medido en la corrida de controles del 07/09: 18 de 73 cuentas con 15 o mas
    # posts se extrajeron por debajo del 60%; usuario_ejemplo2 declaraba 224
    # y dio 11, expocientificactr declaraba 101 y dio 3. Cobertura media de los
    # controles 80% contra 98% de los pacientes: una diferencia TECNICA entre
    # los dos grupos, que el detector de marco muestral leia como si fuera una
    # diferencia real entre las personas.
    # Ahora el scroll sabe cuantos posts dice tener el perfil y sigue insistiendo
    # mientras este lejos de esa cifra, con espera creciente.
    objetivo = _posts_declarados(driver)
    cosechar()
    last_h = driver.execute_script("return document.body.scrollHeight")
    attempts, vueltas, espera = 0, 0, 2.5
    while vueltas < MAX_SCROLLS:
        if objetivo and len(vistos) >= objetivo:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(espera)
        cosechar()  # ANTES de medir: el DOM ya se repinto y aun tiene estas filas
        new_h = driver.execute_script("return document.body.scrollHeight")
        vueltas += 1
        if new_h != last_h:
            attempts, espera = 0, 2.5
            last_h = new_h
            continue
        attempts += 1
        # Si todavia falta mucho para el objetivo, insistir mas y esperar mas:
        # lo que parece el final del grid suele ser una tanda que no ha cargado.
        lejos = objetivo and len(vistos) < objetivo * 0.9
        limite = MAX_INTENTOS_SIN_CAMBIO * 4 if lejos else MAX_INTENTOS_SIN_CAMBIO
        if attempts >= limite:
            break
        if lejos:
            espera = min(espera * 1.5, 8.0)

    cosechar()
    if vueltas >= MAX_SCROLLS:
        print("  Aviso: se alcanzo MAX_SCROLLS (%d), puede faltar cola del perfil" % MAX_SCROLLS)
    cob = ("  (%d declarados, cobertura %.0f%%)" % (objetivo, 100.0 * len(vistos) / objetivo)) if objetivo else ""
    print("  Scroll terminado en %d vueltas: %d enlaces cosechados%s" % (vueltas, len(vistos), cob))
    if objetivo and objetivo >= 15 and len(vistos) < objetivo * 0.6:
        print("  *** AVISO DE COBERTURA: solo %d de %d posts. Este perfil NO es comparable\n"
              "      con los pacientes (cobertura media 98%%). Volver a extraerlo."
              % (len(vistos), objetivo))
    return list(vistos)


# El <video> de Instagram usa MediaSource: su atributo src es un "blob:" que
# solo existe dentro de esa pestana, y og:video aparece en ~1% de las paginas.
# Lo que si queda es el registro de red del navegador: la Performance API lista
# todos los recursos que la pestana descargo, incluido el mp4 del CDN.
_JS_URLS_VIDEO = """
var pat = /\\/o1\\/v\\/t16\\/|\\.mp4($|\\?)/;
return performance.getEntriesByType('resource')
  .filter(function(e){ return pat.test(e.name); })
  .sort(function(a,b){
      return (b.encodedBodySize||b.transferSize||0) - (a.encodedBodySize||a.transferSize||0);
  })
  .map(function(e){ return e.name; })
  .slice(0, 5);
"""

_JS_DESPERTAR_VIDEO = """
var v = document.querySelector('video');
if (!v) { return false; }
try { v.scrollIntoView({block:'center'}); } catch (e) {}
v.muted = true;
try { var p = v.play(); if (p && p.catch) { p.catch(function(){}); } } catch (e) {}
return true;
"""


def limpiar_url_video(u):
    """
    Quita bytestart / byteend de la URL del CDN.

    Instagram sirve el video por DASH: el reproductor pide TROZOS con rango de
    bytes, y eso es lo que ve la Performance API. Si se descarga esa URL tal
    cual sale un fragmento suelto que empieza en `moof` y no lo abre casi ningun
    reproductor, porque le falta la cabecera ftyp/moov. En la corrida del
    28/08/2026 quedaron asi 477 de 497 videos. Sin esos dos parametros el CDN
    devuelve el archivo completo (los 20 videos que llegaron sin rango si
    salieron completos, que es justo la prueba).
    """
    if not u:
        return u
    u = re.sub(r"[?&]bytestart=\d+", "", u)
    u = re.sub(r"[?&]byteend=\d+", "", u)
    # si se elimino el primer parametro, el siguiente tiene que pasar a "?"
    if "?" not in u and "&" in u:
        u = u.replace("&", "?", 1)
    return u


def _meta_content(driver, prop):
    try:
        els = driver.find_elements(By.CSS_SELECTOR, 'meta[property="%s"]' % prop)
        return els[0].get_attribute("content") if els else None
    except Exception:
        return None


def _urls_media_de_post(driver):
    """
    Devuelve {"imagen": url, "video": url_o_None} del post que este abierto.

    La imagen sale de og:image. Para posts de video eso NO es el video, es el
    frame de portada: en la corrida del 27/08/2026 los 90 posts de video se
    guardaron como .jpg justamente por eso, y solo 5 de esos 90 dejaron alguna
    URL de video en el HTML. El resto se perdio.

    Para el video se arranca la reproduccion y despues se lee la Performance
    API, que si registra la descarga real del mp4.
    """
    urls = {"imagen": _meta_content(driver, "og:image"), "video": None}

    directo = _meta_content(driver, "og:video") or _meta_content(driver, "og:video:secure_url")
    if directo:
        urls["video"] = limpiar_url_video(directo)
        return urls

    try:
        hay_video = driver.execute_script(_JS_DESPERTAR_VIDEO)
    except Exception:
        hay_video = False
    if not hay_video:
        return urls

    for _ in range(ESPERA_VIDEO_INTENTOS):
        time.sleep(ESPERA_VIDEO)
        try:
            encontradas = driver.execute_script(_JS_URLS_VIDEO) or []
        except Exception:
            encontradas = []
        if encontradas:
            urls["video"] = limpiar_url_video(encontradas[0])
            break
    return urls


def _es_post_de_video(driver):
    try:
        return bool(driver.find_elements(By.CSS_SELECTOR, "video"))
    except Exception:
        return False


def descargar_media(url, destino):
    """
    Baja el archivo del CDN de Instagram.

    Las URLs llevan un token `oe=` con fecha de caducidad: las de la corrida
    del 27/08/2026 expiraban todas el 1 de septiembre de 2026. Como esa corrida
    no bajo ningun binario, el componente visual de sus 519 posts se pierde en
    cuanto vence el token. Por eso ahora se descarga en el momento.
    """
    if not url:
        return False
    if os.path.exists(destino):
        return True
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        r = requests.get(url, timeout=30, headers={"User-Agent": UA_DESCARGA})
        r.raise_for_status()
        with open(destino, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print("    [media] no se pudo bajar %s: %s" % (os.path.basename(destino), e))
        return False


def parsear_html_perfil(html_path, links_cosechados=None):
    """
    Lee el HTML del perfil ya guardado.

    DEFECTO 3 CORREGIDO (28/08/2026). seguidores / seguidos / publicaciones se
    leen ahora del DOM RENDERIZADO, y og:description queda solo como respaldo.
    Instagram sirve og:description desde un cache que puede tener semanas: en
    la corrida del 27/08/2026, 54 de 56 perfiles comparables NO coincidian con
    lo que mostraba la pagina, y en dos casos el cache decia 0 seguidores
    cuando el DOM decia 32 (Tonygdr) y 680 (usuario_ejemplo17). Se conservan ambos
    valores en campos separados para poder auditar la diferencia.

    De paso se devuelven `estado_cuenta` y `biografia`, que estaban en el HTML
    y nunca llegaban al JSON. `estado_cuenta` es lo que evita que vuelvan a
    quedar perfiles "sin explicar": los marcadores estan medidos contra los 30
    perfiles que si entregaron posts y ninguno dio falso positivo. OJO: se
    buscan sobre el texto visible, ya sin <script>, porque en el HTML crudo
    aparecen dentro del bundle de JavaScript de TODAS las paginas (ese es el
    motivo por el que `is_private` parece un marcador y no lo es).
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    get_meta = lambda p: (tag.get("content") if (tag := soup.find("meta", attrs={"property": p})) else None)
    title, desc = get_meta("og:title"), get_meta("og:description")
    profile_pic = get_meta("og:image")

    m_t = re.search(r"^(.*?)\s+\(@(.*?)\)", title) if title else None
    usuario_tag = (m_t.group(2) if m_t else "") or ""

    # --- enlaces a posts -------------------------------------------------
    # Mandan los cosechados durante el scroll (ver hacer_scroll). Lo que quede
    # en el DOM final se agrega despues como respaldo, sin duplicar.
    links = {}
    for u in (links_cosechados or []):
        links.setdefault(u, None)
    for a in soup.find_all("a", href=True):
        u = _normalizar_link(a["href"])
        if u:
            links.setdefault(u, None)
    # Defecto 5: separar lo que publico el perfil de lo que publico otra cuenta.
    duenio = (usuario_tag or "").lower()
    propios, ajenos = [], []
    for u in links:
        d = _dueno_de_url(u)
        (propios if (not d or not duenio or d == duenio) else ajenos).append(u)
    links = propios if EXCLUIR_POSTS_AJENOS else propios + ajenos

    # --- texto renderizado, sin scripts ----------------------------------
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    # --- metricas: primero el DOM, og:description solo de respaldo -------
    m_dom = re.search(
        r"([\d.,]+\s*[kKmM]?)\s+(?:posts?|publicaciones)\s+"
        r"([\d.,]+\s*[kKmM]?)\s+(?:followers?|seguidores)\s+"
        r"([\d.,]+\s*[kKmM]?)\s+(?:following|seguidos|seguidas)",
        visible, re.I)
    m_og = re.search(
        r"([\d.,]+\s*[kKmM]?)\s+[^,]+,\s*([\d.,]+\s*[kKmM]?)\s+[^,]+,\s*([\d.,]+\s*[kKmM]?)\s+[^,]+",
        desc) if desc else None

    og_followers = m_og.group(1).strip() if m_og else None
    og_following = m_og.group(2).strip() if m_og else None
    og_posts     = m_og.group(3).strip() if m_og else None

    if m_dom:
        posts_n   = m_dom.group(1).strip()
        followers = m_dom.group(2).strip()
        following = m_dom.group(3).strip()
        fuente = "dom"
    else:
        posts_n, followers, following = og_posts, og_followers, og_following
        fuente = "og:description"

    # --- estado de la cuenta (marcadores validados, 0 falsos positivos) ---
    if re.search(r"isn'?t available|no est[aa]\s+disponible|no est[aá] disponible", visible, re.I):
        estado = "no_existe"
    elif re.search(r"This profile is private|Esta cuenta es privada", visible, re.I):
        estado = "privada"
    elif re.search(r"No posts yet|A[uú]n no hay publicaciones", visible, re.I):
        estado = "publica_sin_posts"
    else:
        estado = "publica_con_posts"

    # --- biografia (texto libre que nunca llegaba al JSON) ---------------
    bio = ""
    if m_dom:
        resto = visible[m_dom.end():]
        bio = re.split(
            r"\b(?:Follow Back|Following|Follow|Message|Requested|Suggested for you|"
            r"No posts yet|This profile is private|Seguir|Mensaje|Solicitado)\b",
            resto)[0].strip()
        if usuario_tag:
            bio = re.sub(r"\b%s\s*$" % re.escape(usuario_tag), "", bio, flags=re.I).strip()
        bio = bio[:500]

    return {
        "username": usuario_tag or None,
        "nombre": m_t.group(1) if m_t else None,
        "followers": followers, "following": following, "posts": posts_n,
        "metricas_fuente": fuente,
        "followers_og": og_followers, "following_og": og_following, "posts_og": og_posts,
        "estado_cuenta": estado,
        "biografia": bio,
        "profile_pic": profile_pic,
        "links_posts": links,
        "links_otras_cuentas": ajenos,
    }


def extraer_caption_post(driver):
    """
    Antes, si el DOM encontraba un texto >=15 caracteres (típico cuando SÍ
    hay caption), la función retornaba de inmediato forzando likes_text,
    comments_text, username_post y fecha_text a None — nunca llegaba a leer
    el og:description que sí los tenía. Y cuando NO había caption, el
    og:description no trae el bloque ': "caption"' final, así que la regex
    completa (que exigía ese bloque para matchear) fallaba entera y también
    dejaba likes/comments en None, aunque el texto sí los incluyera.
    Ahora likes/comments/username/fecha y caption se extraen con dos
    regex independientes sobre el mismo og:description: una cubre el
    encabezado ("X likes, Y comments - usuario el FECHA"), que siempre está
    presente tenga o no caption, y la otra solo el caption entre comillas,
    que puede faltar sin afectar a la primera.
    """
    caption_dom = None
    for xpath in ["//article//h1", "//article//ul//span", "//article//div//span"]:
        try:
            texts = [el.text.strip() for el in driver.find_elements(By.XPATH, xpath) if len(el.text.strip()) >= 15]
            if texts:
                caption_dom = texts[0]
                break
        except:
            pass

    try:
        desc = driver.find_element(By.XPATH, "//meta[@property='og:description']").get_attribute("content")
        desc = re.sub(r"\s+", " ", desc)
        # El separador de fecha depende del idioma en que Instagram sirva la
        # meta-descripcion: "el 5 de marzo de 2026" (es) u "on March 5, 2026"
        # (en). Antes solo se contemplaba el espanol, asi que en las corridas
        # servidas en ingles el grupo 3 se comia el resto de la cadena y
        # username_post quedaba como "usuario on March 5, 2026: \"caption...\"".
        # El usuario es \w y puntos, nada mas: acotarlo evita que se desborde.
        m_head = re.search(
            r"^(.*?),\s*(.*?)\s*-\s*([A-Za-z0-9._]{1,30})\s+(?:el|on)\s+([^:]*)", desc)
        m_cap = re.search(r'"(.*)"\s*\.?\s*$', desc)
        return {
            "likes_text":    m_head.group(1).strip() if m_head else None,
            "comments_text": m_head.group(2).strip() if m_head else None,
            "username_post": m_head.group(3).strip() if m_head else None,
            "fecha_text":    m_head.group(4).strip() if m_head else None,
            "caption":       caption_dom or (m_cap.group(1) if m_cap else None),
            "caption_raw":   desc,
        }
    except:
        return {
            "likes_text": None, "comments_text": None, "username_post": None,
            "fecha_text": None, "caption": caption_dom, "caption_raw": None,
        }

def expandir_respuestas(driver):
    """
    Hace clic en todos los botones 'Ver las X respuestas' del post actual.
    NO hace scroll — el scroll de página entera saca al scraper del post de IG.
    Usa execute_script click para evitar problemas de elementos fuera del viewport.
    """
    try:
        intentos = 0
        while intentos < 8:
            botones = driver.find_elements(
                By.XPATH,
                "//span[starts-with(normalize-space(.), 'Ver las') and "
                "contains(normalize-space(.), 'respuesta')]"
                " | //span[starts-with(normalize-space(.), 'Ver') and "
                "contains(normalize-space(.), 'respues')]"
            )
            visibles = [b for b in botones if b.is_displayed()]
            if not visibles:
                break
            clicks = 0
            for b in visibles:
                try:
                    driver.execute_script("arguments[0].scrollIntoView(true);", b)
                    time.sleep(0.3)
                    driver.execute_script("arguments[0].click();", b)
                    clicks += 1
                    time.sleep(1.0)
                except:
                    pass
            if clicks == 0:
                break
            intentos += 1
            time.sleep(1.0)
    except Exception as e:
        print(f"Aviso expandiendo respuestas: {e}")


def parsear_comentarios_html(page_source):
    """
    Extrae comentarios del JSON embebido en <script type="application/json">
    del HTML del post (IG los guarda ahí como JSON válido, no como texto
    suelto). Antes esto se hacía con una regex que buscaba "username" -> "pk"
    -> "text" -> "parent_comment_id" en ese orden y a una distancia máxima de
    caracteres: si el orden de las claves cambiaba (algo muy común en
    replies, que traen campos extra como "child_comment_count") o el texto
    superaba el límite de caracteres esperado, la regex simplemente no
    matcheaba y esa respuesta se perdía en silencio.
    Ahora se usa json.loads() + recorrido recursivo (_walk_json), que
    encuentra cada nodo-comentario sin importar el orden de sus claves ni la
    profundidad de anidamiento. Como bonus, json.loads ya decodifica
    correctamente los \\uXXXX de IG (emojis, tildes, etc.), así que ya no
    hace falta ningún hack manual de doble-decodificación.
    """
    soup = BeautifulSoup(page_source, "html.parser")

    vistos_pk      = set()
    comentarios_raw = []

    for script in soup.find_all("script", attrs={"type": "application/json"}):
        try:
            data = json.loads(script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        for nodo in _walk_json(data):
            user = nodo.get("user")
            # Un comentario real de IG siempre trae user.username + pk + text
            # + created_at + comment_like_count. Antes solo se exigían los
            # primeros 3, y eso hacía match con algún nodo que NO es un
            # comentario (ej. contexto del usuario logueado) — se detectó
            # en un post que en realidad tiene 0 comentarios ("Todavía no
            # hay comentarios") pero el script igual reportaba 1.
            if not (
                isinstance(user, dict) and "username" in user
                and "pk" in nodo and "text" in nodo
                and "created_at" in nodo and "comment_like_count" in nodo
            ):
                continue

            pk = str(nodo["pk"])
            if pk in vistos_pk:
                continue
            vistos_pk.add(pk)

            texto = nodo.get("text") or ""
            parent = nodo.get("parent_comment_id")
            comentarios_raw.append({
                "username": user["username"],
                "pk":       pk,
                "text":     texto.strip() if texto.strip() else "[imagen/gif]",
                "parent":   str(parent) if parent not in (None, "", "null") else None,
            })

    return comentarios_raw


def _extraer_replies_dom(driver):
    """
    Extrae las RESPUESTAS (replies) a comentarios directamente del DOM ya
    renderizado, después de expandir_respuestas().

    Por qué el método anterior (parsear_comentarios_html sobre el script
    JSON) nunca las capturaba: ese <script type="application/json"> es el
    payload estático que Instagram genera al cargar la página (SSR) y solo
    trae los comentarios raíz visibles de entrada. Al hacer clic en 'Ver
    respuestas', IG pide las replies por AJAX y solo actualiza la vista (el
    DOM real que ve el usuario) — nunca vuelve a escribir esos datos en el
    script original.

    IMPORTANTE (corregido tras revisar un HTML real): un post sin ningún
    comentario ("Todavía no hay comentarios") reportaba igual 1 "respuesta"
    falsa, porque la heurística de respaldo aceptaba cualquier bloque con 2+
    enlaces de usuario — y esos existen en cualquier post (avatares de "Me
    gusta", cuentas sugeridas, nav). Ahora TODO bloque candidato debe
    contener además la palabra "Responder"/"Reply" (el botón que Instagram
    pone en cada comentario/respuesta real); si esa palabra no aparece en
    ningún lado del HTML, no hay comentarios reales que procesar y la
    función corta de inmediato.

    Se usan DOS estrategias, en este orden, ambas exigiendo "Responder":
    A) Mención visible: se busca el símbolo "@" ya sea DENTRO del enlace de
       usuario (<a>@fulano</a>) o como texto suelto justo antes del enlace
       (fulano @<a>fulano</a>), porque no sabemos con certeza cuál de las
       dos usa Instagram sin ver el HTML real.
    B) Respaldo estructural: si (A) no encuentra nada, se asume que todo
       bloque de comentario con 2 o más enlaces de usuario propios (sin
       contar los que están dentro de una sub-lista anidada) Y que contenga
       "Responder"/"Reply" en su texto, es una respuesta.
    """
    soup = BeautifulSoup(driver.page_source, "html.parser")
    patron_usuario_raw = re.compile(r"^/[A-Za-z0-9_.]{1,30}/$")
    patron_responder = re.compile(r"\bResponder\b|\bReply\b")
    replies, vistos = [], set()

    # Rutas reservadas de Instagram que matchean el mismo patrón que un
    # username (ej. /reels/) pero NO son cuentas de usuario. Se detectó que
    # "/reels/" (el ícono de navegación) se colaba como si fuera un autor.
    RUTAS_RESERVADAS = {
        "reels", "reel", "explore", "accounts", "direct", "stories", "tv",
        "p", "legal", "about", "developer", "challenge", "emails",
        "session", "graphql", "api", "directory", "hashtag", "location",
        "tags", "ads", "lite", "web", "settings", "create",
    }

    def patron_usuario(href):
        m = patron_usuario_raw.match(href)
        if not m:
            return False
        return href.strip("/").lower() not in RUTAS_RESERVADAS

    def _enlaces_usuario(tag):
        return [a for a in tag.find_all("a", href=True) if patron_usuario(a["href"])]

    if not patron_responder.search(soup.get_text(" ")):
        # No hay ni un solo botón "Responder"/"Reply" en toda la página =>
        # el post no tiene comentarios reales (o aún no cargaron). Evita
        # que cualquier heurística busque "respuestas" donde no las hay.
        print("    [debug respuestas] no se encontró 'Responder/Reply' en la página — no hay comentarios reales")
        return []

    def _limpiar_texto(bloque, autor, parent_username):
        texto = bloque.get_text(" ", strip=True)
        texto = re.sub(rf"^{re.escape(autor)}\s*", "", texto, count=1)
        # quitar el sello de tiempo que IG pone entre el autor y el texto (ej. "5 sem")
        texto = re.sub(r"^\d+\s*(?:sem|semanas?|w|d|días?|h|horas?|min)\b\s*", "", texto, count=1)
        texto = re.sub(rf"^@?{re.escape(parent_username)}\s*", "", texto, count=1).strip()
        # quitar el contador de "me gusta" (ej. "milagros 1 Me gusta" -> "milagros Me gusta")
        texto = re.sub(r"\s+\d+\s+(?=Me gusta\b|Like\b|Responder\b|Reply\b)", " ", texto)
        texto = re.split(r"\s+(?:\d+\s*(?:sem|w|semanas?|d|días?|h|horas?|min)\b|Responder|Reply|Me gusta|Like)\b", texto)[0]
        return texto.strip()

    def _agregar(autor, parent_username, bloque):
        if autor == parent_username:
            return
        texto_bloque = bloque.get_text(" ", strip=True)
        if len(texto_bloque) > 400:
            # Un comentario/respuesta real de IG es corto. Un bloque tan
            # largo significa que el ascenso por ancestros se pasó de nivel
            # y fusionó el comentario con otra sección de la página (nav,
            # personas etiquetadas en la foto, cuentas sugeridas, etc.) —
            # se detectó justo así con el enlace de navegación "/reels/".
            return
        if not patron_responder.search(texto_bloque):
            return  # el bloque candidato no tiene botón Responder/Reply -> no es un comentario
        texto = _limpiar_texto(bloque, autor, parent_username)
        if not texto:
            return
        clave = (autor, parent_username, texto)
        if clave in vistos:
            return
        vistos.add(clave)
        replies.append({"autor": autor, "texto": texto, "parent_username": parent_username})

    # --- Estrategia A: mención visible con "@" ---
    # En el DOM real de Instagram el enlace del AUTOR y el enlace de la
    # MENCIÓN casi nunca están en el mismo <div> inmediato (hay ~4 niveles
    # de <div> intermedios por las clases atómicas de Meta). Por eso ya no
    # se usa find_parent (1 solo nivel): se sube por los ancestros hasta
    # encontrar el primer nivel que contenga AMBOS enlaces de usuario Y la
    # palabra "Responder"/"Reply" — ese es el contenedor real de ese
    # comentario/respuesta, sin importar cuántos <div> de por medio haya.
    for enlace in soup.find_all("a", href=patron_usuario):
        texto_enlace = enlace.get_text(strip=True)
        antes = enlace.previous_sibling
        texto_antes = antes.strip() if isinstance(antes, str) else ""
        es_mencion = texto_enlace.startswith("@") or texto_antes.endswith("@")
        if not es_mencion:
            continue

        bloque = None
        nivel = enlace.parent
        for _ in range(10):  # tope de seguridad para no subir hasta la raíz del documento
            if nivel is None:
                break
            hrefs_aqui = {a["href"] for a in nivel.find_all("a", href=patron_usuario)}
            if len(hrefs_aqui) >= 2 and patron_responder.search(nivel.get_text(" ")):
                bloque = nivel
                break
            nivel = nivel.parent
        if not bloque:
            continue

        enlaces = bloque.find_all("a", href=patron_usuario)
        autor_candidatos = [a for a in enlaces if a["href"] != enlace["href"]]
        if not autor_candidatos:
            continue

        autor = autor_candidatos[0]["href"].strip("/")
        parent_username = enlace["href"].strip("/")
        _agregar(autor, parent_username, bloque)

    # --- Estrategia B (respaldo): 2+ enlaces de usuario propios en el bloque ---
    if not replies:
        candidatos = soup.find_all("li") or soup.find_all("div")
        for bloque in candidatos:
            sub_listas = bloque.find_all(["ul", "ol"])
            enlaces_anidados = {a for sub in sub_listas for a in sub.find_all("a", href=patron_usuario)}
            enlaces = [a for a in bloque.find_all("a", href=patron_usuario) if a not in enlaces_anidados]
            if len(enlaces) < 2:
                continue
            autor = enlaces[0]["href"].strip("/")
            parent_username = enlaces[1]["href"].strip("/")
            _agregar(autor, parent_username, bloque)

    print(f"    [debug respuestas] estrategia A/B encontró {len(replies)} respuesta(s) en el DOM")
    return replies


def _guardar_dom_debug(driver, shortcode):
    if not DEBUG_GUARDAR_DOM:
        return
    try:
        carpeta = os.path.join(RESULTADOS_DIR, "debug_dom")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, f"{shortcode or 'post'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"    [debug] DOM guardado en: {ruta}")
    except Exception as e:
        print(f"    [debug] no se pudo guardar DOM: {e}")


def extraer_comentarios_post(driver, caption_actual, usuario, url_post=None):
    """
    Extrae comentarios raíz desde el script JSON SSR (parsear_comentarios_html)
    y respuestas desde el DOM renderizado tras expandir_respuestas() (ver
    _extraer_replies_dom para el porqué de esta separación).
    """
    comentarios_raw = parsear_comentarios_html(driver.page_source)

    expandir_respuestas(driver)
    time.sleep(1.5)  # dar tiempo a que el DOM termine de pintar las replies

    _guardar_dom_debug(driver, _extraer_shortcode(url_post))

    # Refrescar raíces por si el SSR inicial no traía todas (algunos posts
    # solo muestran "Ver los N comentarios" y cargan las raíces también por
    # AJAX) — nos quedamos con el set más completo.
    comentarios_raw_2 = parsear_comentarios_html(driver.page_source)
    if len(comentarios_raw_2) > len(comentarios_raw):
        comentarios_raw = comentarios_raw_2

    # Filtrar el caption del owner — mismo texto que caption_actual
    if caption_actual:
        cap_norm = caption_actual.strip()
        comentarios_raw = [
            c for c in comentarios_raw
            if c["text"] != cap_norm and c["text"][:40] not in cap_norm
        ]

    resultado = []
    autor_a_cmt_id = {}  # último comment_id visto por autor (para linkear replies por mención)
    cmt_counter = 0

    for c in comentarios_raw:
        cmt_counter += 1
        cmt_id = f"cmt_{cmt_counter}"
        autor_a_cmt_id[c["username"]] = cmt_id
        resultado.append({
            "comment_id":        cmt_id,
            "autor":             c["username"],
            "texto":             c["text"],
            "es_reply":          False,
            "parent_comment_id": "",
        })

    for r in _extraer_replies_dom(driver):
        cmt_counter += 1
        cmt_id = f"cmt_{cmt_counter}"
        parent_id = autor_a_cmt_id.get(r["parent_username"], "")
        resultado.append({
            "comment_id":        cmt_id,
            "autor":             r["autor"],
            "texto":             r["texto"],
            "es_reply":          True,
            "parent_comment_id": parent_id,
        })
        autor_a_cmt_id[r["autor"]] = cmt_id  # por si alguien responde a esta respuesta

    return resultado


def procesar_perfil(driver, item):
    f_i, f_f = item["f_inicio"], item["f_fin"]
    print(f"\nProcesando: {item['usuario']} (Rango: {f_i.date()} a {f_f.date()})")
    
    driver.get(item["url"])
    time.sleep(5)
    links_cosechados = hacer_scroll(driver)   # defecto 1: cosecha durante el scroll
    
    h_path = os.path.join(RESULTADOS_DIR, f"perfil_{limpiar_nombre_archivo(item['usuario'])}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    os.makedirs(RESULTADOS_DIR, exist_ok=True)
    with open(h_path, "w", encoding="utf-8") as f: f.write(driver.page_source)
    
    info = parsear_html_perfil(h_path, links_cosechados=links_cosechados)
    posts_data = []
    for i, link in enumerate(info["links_posts"], 1):
        driver.get(link)
        time.sleep(ESPERA_CAPTION)
        f_p = obtener_fecha_post(driver, url_post=link)

        # Verificar rango — el <time> de IG a veces devuelve fecha de edición.
        # Si cae fuera de rango, leer también la fecha_text del caption como
        # respaldo (que muestra la fecha original de publicación).
        if not f_p or not (f_i <= f_p <= f_f):
            cap_check = extraer_caption_post(driver)
            fecha_txt  = (cap_check.get("fecha_text") or "") if cap_check else ""
            try:
                from dateutil import parser as dp
                f_check = dp.parse(fecha_txt, fuzzy=True).replace(tzinfo=None) if fecha_txt else None
                if not f_check or not (f_i <= f_check <= f_f):
                    print(f"[{i}] Fuera de rango ({f_p} / '{fecha_txt}') — saltando")
                    continue
                f_p = f_check
                cap = cap_check
            except Exception:
                print(f"[{i}] Fuera de rango ({f_p}) — saltando")
                continue
        else:
            cap = extraer_caption_post(driver)

        caption_texto = cap.get("caption") if cap else None
        comms = extraer_comentarios_post(driver, caption_texto, item["usuario"], url_post=link)
        
        # Defecto 4: bajar imagen Y video AHORA. Las URLs del CDN caducan.
        media_url, media_local, video_url, video_local = None, "", None, ""
        if DESCARGAR_MEDIA:
            u = _urls_media_de_post(driver)
            media_url, video_url = u.get("imagen"), u.get("video")
            sc = _extraer_shortcode(link) or ("post%03d" % i)
            carpeta = os.path.join(MEDIA_SUBDIR, limpiar_nombre_archivo(item["usuario"]))
            rel_img = os.path.join(carpeta, "%s.jpg" % sc)
            if descargar_media(media_url, os.path.join(RESULTADOS_DIR, rel_img)):
                media_local = rel_img.replace("\\", "/")
            if video_url:
                rel_vid = os.path.join(carpeta, "%s.mp4" % sc)
                if descargar_media(video_url, os.path.join(RESULTADOS_DIR, rel_vid)):
                    video_local = rel_vid.replace("\\", "/")

        # Defecto 5: dejar por escrito de quien es el post.
        autor_post = _dueno_de_url(link)
        es_del_perfil = (not autor_post) or autor_post == (item["usuario"] or "").lower()

        posts_data.append({
            "url": link, 
            "fecha_post_iso": f_p.isoformat(), 
            **cap,
            "autor_post": autor_post or (item["usuario"] or "").lower(),
            "es_del_perfil": es_del_perfil,
            "media_url": media_url,
            "media_local": media_local,
            "video_url": video_url,
            "video_local": video_local,
            "comments": comms
        })
        print(f"[{i}] Post capturado: {f_p.date()} | {len(comms)} comments"
              + (" | img ok" if media_local else "")
              + (" | video ok" if video_local else (" | VIDEO NO CAPTURADO" if video_url is None and media_local and _es_post_de_video(driver) else ""))
              + ("" if es_del_perfil else f"  <-- OJO: es de @{autor_post}, no del paciente"))

    posts_data.sort(key=lambda p: p.get("fecha_post_iso") or "", reverse=True)

    n_ajenos = sum(1 for p in posts_data if not p.get("es_del_perfil", True))
    if n_ajenos:
        print(f"  Aviso: {n_ajenos} de {len(posts_data)} posts son de otras cuentas "
              f"(colaboraciones o etiquetados). Quedan marcados con es_del_perfil=False.")

    res = {
        **item, 
        **info, 
        "rango_fechas": {"inicio": f_i.strftime("%Y-%m-%d"), "fin": f_f.strftime("%Y-%m-%d")}, 
        "posts_data": posts_data,
        "f_inicio": f_i.isoformat(), 
        "f_fin": f_f.isoformat()
    }
    save_json(res, f"perfil_{limpiar_nombre_archivo(item['usuario'])}")
    return res

def _arg(nombre, defecto=None):
    """Lee `--nombre VALOR` de la linea de comandos."""
    if nombre in sys.argv:
        i = sys.argv.index(nombre)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return defecto


def _filtrar_usuarios(usuarios):
    """
    Permite correr por lotes sin editar el CSV a mano. Hace falta porque la
    corrida completa son ~1,530 posts en una sola sesion de la misma cuenta,
    y eso invita a que Instagram meta un throttle a media corrida.

        --solo MIND0001,usuario_ejemplo8    solo esos (por id o por usuario)
        --desde 1 --hasta 20              los primeros 20 del CSV
    """
    solo = _arg("--solo")
    if solo:
        claves = {x.strip().lower() for x in solo.split(",") if x.strip()}
        usuarios = [u for u in usuarios
                    if str(u.get("id", "")).strip().lower() in claves
                    or str(u.get("usuario", "")).strip().lower() in claves]
        faltan = claves - {str(u.get("id", "")).strip().lower() for u in usuarios} \
                        - {str(u.get("usuario", "")).strip().lower() for u in usuarios}
        if faltan:
            print("Aviso: no encontre en el CSV -> %s" % ", ".join(sorted(faltan)))
    if not usuarios:
        return usuarios
    desde = max(int(_arg("--desde", 1)), 1)
    hasta = int(_arg("--hasta", len(usuarios)))
    return usuarios[desde - 1:hasta]


def main():
    ruta_csv = _arg("--csv", CSV_PATH)
    usuarios = cargar_usuarios(ruta_csv)
    if not usuarios: return print("No hay usuarios en %s." % ruta_csv)

    usuarios = _filtrar_usuarios(usuarios)
    if not usuarios: return print("El filtro no dejo ningun perfil por procesar.")

    print("\nCSV      : %s" % ruta_csv)
    print("Perfiles : %d  ->  %s%s" % (
        len(usuarios), ", ".join(u["usuario"] for u in usuarios[:8]),
        " ..." if len(usuarios) > 8 else ""))
    print("Media    : %s\n" % ("se descarga" if DESCARGAR_MEDIA else "DESACTIVADA"))

    ejecucion = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_ckpt = os.path.join(RESULTADOS_DIR, "global_en_curso.json")

    resultados_totales = []
    if "--reanudar" in sys.argv and os.path.exists(ruta_ckpt):
        try:
            previo = json.load(open(ruta_ckpt, encoding="utf-8")).get("resultados", [])
            hechos = {str(r.get("id")) for r in previo}
            antes = len(usuarios)
            usuarios = [u for u in usuarios if str(u.get("id")) not in hechos]
            resultados_totales = previo
            print("Reanudando: %d perfiles ya estaban hechos, faltan %d de %d.\n"
                  % (len(hechos), len(usuarios), antes))
            if not usuarios:
                return print("No queda nada por procesar.")
        except Exception as e:
            print("No pude leer el checkpoint (%s). Empiezo de cero.\n" % e)

    driver = webdriver.Chrome() 
    wait = WebDriverWait(driver, ESPERA_LOGIN)
    anomalias = 0

    try:
        iniciar_sesion(driver, wait)
        for n, item in enumerate(usuarios, 1):
            print("\n===== [%d/%d] =====" % (n, len(usuarios)))
            try:
                res = procesar_perfil(driver, item)
            except Exception as e:
                print(f"Error en {item['usuario']}: {e}")
                res = {**item, "error": str(e), "posts_data": []}

            res = _serializable(res)
            resultados_totales.append(res)
            # Checkpoint despues de CADA perfil: antes el global solo se escribia
            # al final, asi que una caida en la hora 4 se llevaba todo por delante.
            save_json_en({"ejecucion": ejecucion,
                          "completados": len(resultados_totales),
                          "resultados": resultados_totales}, ruta_ckpt)

            if res.get("estado_cuenta") == "publica_con_posts" and not (res.get("links_posts") or []):
                anomalias += 1
                print("  Aviso: la pagina dice que tiene publicaciones pero no se "
                      "cosecho ningun enlace (%d seguidos)." % anomalias)
            else:
                anomalias = 0

            if anomalias >= LIMITE_ANOMALIAS:
                print("\n*** %d perfiles seguidos sin enlaces. Esto huele a limite de "
                      "Instagram. ***" % anomalias)
                print("    Corto aqui para no llenar el dataset de vacios.")
                print("    Espera un rato y continua con la MISMA orden mas --reanudar\n")
                break

        save_json({"resultados": resultados_totales}, "global")
        # Aquí se aplica la anonimización únicamente para el JSON anónimo
        # El conjunto de handles de TODA la corrida, para que el anonimo de un
        # perfil no deje al descubierto a otro perfil de la misma corrida.
        handles_corrida = {(r.get("usuario") or r.get("username") or "").strip()
                           for r in resultados_totales}
        handles_corrida |= {(p.get("autor_post") or "")
                            for r in resultados_totales for p in (r.get("posts_data") or [])}
        anonimos = [construir_resultado_anonimo(r, handles_corrida) for r in resultados_totales]
        # Defecto 2: no se confia en la anonimizacion, se verifica antes de escribir.
        fugas = verificar_anonimato(anonimos, resultados_totales)
        if fugas:
            # Antes se escribia igual con el nombre normal y la alerta quedaba
            # sepultada entre miles de lineas de consola. Ahora el propio nombre
            # del archivo avisa, y ademas queda el detalle por escrito.
            ruta = save_json({"resultados": anonimos}, "global_anonimo_CON_FUGAS")
            ruta_txt = os.path.join(RESULTADOS_DIR, "fugas_anonimato.txt")
            with open(ruta_txt, "w", encoding="utf-8") as fh:
                fh.write("Usuarios reales encontrados en el export anonimo\n")
                fh.write("Archivo: %s\n\n" % os.path.basename(ruta))
                for u, n in fugas:
                    fh.write("%-30s %d apariciones\n" % (u, n))
            print("\n" + "!" * 66)
            print("EL ARCHIVO ANONIMO TIENE FUGAS. Se guardo como:")
            print("   %s" % os.path.basename(ruta))
            print("Detalle en: %s" % ruta_txt)
            print("NO lo compartas hasta corregirlo.")
            print("!" * 66 + "\n")
        else:
            save_json({"resultados": anonimos}, "global_anonimo")
        if "--sin-pausa" not in sys.argv:
            input("Terminado. Enter para cerrar...")
        else:
            print("Terminado.")
    finally: driver.quit()

if __name__ == "__main__": main()