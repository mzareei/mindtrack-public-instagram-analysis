# -*- coding: utf-8 -*-
"""
Triaje: decide en ~15 s por perfil, con la sola pagina del perfil.

Tres veredictos de aprobacion, segun de donde sale la evidencia de edad:

  aprobado_bio          la persona escribio su edad en la biografia
  aprobado_institucion  una escuela la nombro alumna en un post propio
                        (tipo_evidencia="institucion" en la cosecha), la cuenta
                        es personal, cabe en la envolvente y la bio no la
                        contradice
  pendiente_captions    personal, en envolvente, sin edad en la bio y sin
                        evidencia institucional: pasa a verificar_captions.py

Todo lo demas se descarta con su motivo. Cada aprobado guarda QUE evidencia lo
sostiene, porque eso va en la tabla del articulo.

Uso:
    python ig/control/triaje.py [--csv ig/control/candidatos_formato.csv]
                                [--reanudar] [--limite N] [--dormir-al-limite]
"""

import csv, json, os, random, sys, time
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))

import inferir_edad as ie
from util import numero, categoria_profesional, es_organizacion, fuera_de_jalisco, id_control

PAUSA = (6.0, 11.0)
ESPERA_CARGA = 3.5
LIMITE_ANOMALIAS = 8
SIESTA_LIMITE_S = 45 * 60      # si Instagram corta, dormir esto y seguir

SALIDA = os.path.join(DIR, "triaje.csv")
APROBADOS = os.path.join(DIR, "candidatos_aprobados_formato.csv")
PENDIENTES = os.path.join(DIR, "candidatos_pendientes_formato.csv")
CKPT = os.path.join(DIR, "triaje_en_curso.json")
TMP_HTML = os.path.join(DIR, "_triaje_tmp.html")

BANDAS_INSTITUCION = {"15-18": (15, 18), "18-24": (18, 24), "15-24": (15, 24), "12-15": (12, 15)}

# Las escuelas tambien etiquetan a maestros, directivos y personal. Una bio
# con titulo profesional o con rol de padre/madre contradice la evidencia
# "alumno de prepa". Mejor perder un control que meter a una maestra.
import re as _re
ROL_ADULTO_FUERTE = _re.compile(
    r"\b(mtr[oa]\.?|maestr[oa]|profe(?:sor[a]?)?|docente|director[a]?|coordinador[a]?|"
    r"dr[a]?\.|lic\.|ing\.|psic\.|arq\.|cp\.|abogad[oa]|enfermer[oa]|m[eé]dic[oa]|"
    r"orientador[a]?|prefect[oa]|secretari[oa] academic|rector[a]?|investigador[a]?"
    r"|cient[ií]fic[oa]|te[oó]ric[oa]|catedr[aá]tic[oa]|acad[eé]mic[oa]|jef[ea] de|gerente"
    r"|fundador[a]?|\bceo\b|empresari[oa]|consultor[a]?|terapeuta|psic[oó]log[oa]|nutri[oó]log[oa])", _re.I)
ROL_ADULTO_DEBIL = _re.compile(
    r"\b(mam[aá] de|pap[aá] de|espos[oa]|mis hij[oa]s|mi hij[oa]|abuel[oa])\b", _re.I)
EDAD_ADULTA = _re.compile(r"(?:^|[^0-9A-Za-zÀ-ÿ])([3-7][0-9])(?:\s*(?:años|anios|anos)\b|(?=[^0-9A-Za-zÀ-ÿ]|$))")


def contradiccion_adulta(bio, banda):
    """Devuelve el motivo si la bio delata a un adulto que no puede ser alumno
    de esa banda, o "" si no hay contradiccion."""
    b = bio or ""
    # "estudiante de ing. mecatronica" no es un ingeniero: si la bio se declara
    # estudiante, el titulo abreviado no cuenta como rol de personal.
    se_declara_alumno = _re.search(r"\b(estudiante|alumn[oa]|estudio\b|estudiando)", b, _re.I)
    if not se_declara_alumno and ROL_ADULTO_FUERTE.search(b):
        return "bio con titulo o rol de personal (%s)" % ROL_ADULTO_FUERTE.search(b).group(0)
    if banda == "15-18" and ROL_ADULTO_DEBIL.search(b):
        return "bio con rol adulto (%s)" % ROL_ADULTO_DEBIL.search(b).group(0)
    m = EDAD_ADULTA.search(ie._fechas_a_enmascarar(ie._normalizar(b)))
    if m:
        return "bio declara %s años" % m.group(1)
    return ""


def cargar_envolvente():
    r = os.path.join(DIR, "envolvente_control.json")
    if not os.path.exists(r):
        sys.exit("Falta envolvente_control.json. Corre: python ig/control/envolvente.py")
    return json.load(open(r, encoding="utf-8"))


def cargar_evidencia():
    """usuario -> (tipo_evidencia, semilla, shortcode, banda) desde candidatos.csv"""
    ruta = os.path.join(DIR, "candidatos.csv")
    out = {}
    if os.path.exists(ruta):
        for c in csv.DictReader(open(ruta, encoding="utf-8-sig")):
            out[c["usuario"].lower()] = (c.get("tipo_evidencia", "ninguna"), c.get("semilla", ""),
                                         c.get("shortcode_evidencia", ""), c.get("banda_esperada", ""))
    return out


def _handles_semilla():
    fuera = set()
    try:
        import cosechar_candidatos as cc
        fuera |= {s_["valor"].lower() for s_ in cc.SEMILLAS}
        ruta = os.path.join(DIR, "semillas_descubiertas.txt")
        if os.path.exists(ruta):
            fuera |= {l.split(",")[0].strip().lower() for l in open(ruta, encoding="utf-8")
                      if l.strip() and not l.startswith("#")}
    except Exception:
        pass
    return fuera


SEMILLAS_SET = None


def evaluar(datos, env, evidencia=None, aceptar_baja=False):
    """Devuelve dict con veredicto, motivo, edad, banda, confianza, evidencia."""
    global SEMILLAS_SET
    if SEMILLAS_SET is None:
        SEMILLAS_SET = _handles_semilla()
    if (datos.get("username") or "").lower() in SEMILLAS_SET:
        return {"veredicto": "rechazado", "motivo": "es una semilla (cuenta institucional)",
                "edad": None, "banda": "", "confianza": "", "evidencia": ""}
    ev_tipo, ev_semilla, ev_sc, ev_banda = evidencia or ("ninguna", "", "", "")
    R = lambda v, m, **k: {"veredicto": v, "motivo": m, "edad": k.get("edad"),
                           "banda": k.get("banda", ""), "confianza": k.get("conf", ""),
                           "evidencia": k.get("ev", "")}

    estado = datos.get("estado_cuenta")
    if estado != "publica_con_posts":
        return R("rechazado", estado or "sin estado")
    cat = categoria_profesional(datos.get("biografia", ""))
    if cat:
        return R("rechazado", "cuenta profesional (%s)" % cat.lower())
    org = es_organizacion(datos.get("biografia", ""), datos.get("username", "") or "")
    if org:
        return R("rechazado", "organizacion: %s" % org)
    lugar = fuera_de_jalisco(datos.get("biografia", ""))
    if lugar:
        return R("rechazado", "fuera de Jalisco (%s)" % lugar)
    # Segunda red: el nombre de usuario. coordinacion_indu_cucei o
    # usuario_ejemplo7 no llevan categoria pero tampoco son alumnos.
    try:
        from filtrar_candidatos import INSTITUCIONAL as _INST
        u_ = (datos.get("username") or "")
        if u_ and _INST.search(u_):
            return R("rechazado", "nombre de usuario institucional o con titulo (%s)" % _INST.search(u_).group(0))
    except ImportError:
        pass
    seg = numero(datos.get("followers"))
    lim = env["seguidores"]["limite_admision"]
    if not (lim[0] <= seg <= lim[1]):
        return R("rechazado", "seguidores fuera de envolvente (%d)" % seg)
    n_posts = numero(datos.get("posts"))
    limp = env["posts_totales"]["limite_admision"]
    if n_posts and not (limp[0] <= n_posts <= limp[1]):
        return R("rechazado", "numero de posts fuera de envolvente (%d)" % n_posts)

    res = ie.inferir(bio=datos.get("biografia", ""), nombre=datos.get("nombre", "") or "",
                     usuario=datos.get("username", "") or "")
    edad_bio = res["edad_estimada"] if res["confianza"] in ("alta", "media") else None

    # 1) Edad en la bio, confianza alta/media.
    if edad_bio is not None:
        if ie.EDAD_MIN <= edad_bio <= ie.EDAD_MAX:
            return R("aprobado_bio", "aprobado: edad en bio", edad=edad_bio,
                     banda=ie.banda_de(edad_bio), conf=res["confianza"], ev="bio: %s" % res["evidencia"])
        return R("rechazado", "edad fuera de 15-29 (%d)" % edad_bio)

    # 2) Evidencia institucional: una escuela la nombro alumna.
    if ev_tipo == "institucion" and ev_banda in BANDAS_INSTITUCION:
        lo, hi = BANDAS_INSTITUCION[ev_banda]
        # Si la bio da una edad con confianza baja que contradice la banda por
        # mucho, se rechaza: mejor perder un control que meter a un maestro.
        if res["edad_estimada"] and not (lo - 3 <= res["edad_estimada"] <= hi + 3):
            return R("rechazado", "bio contradice evidencia institucional (%s vs %s)"
                     % (res["edad_estimada"], ev_banda))
        contra = contradiccion_adulta(datos.get("biografia", ""), ev_banda)
        if contra:
            return R("rechazado", "contradice evidencia institucional: %s" % contra)
        if hi < ie.EDAD_MIN:
            return R("rechazado", "banda institucional por debajo de 15 (%s)" % ev_banda)
        return R("aprobado_institucion", "aprobado: etiquetada por @%s" % ev_semilla,
                 edad=(lo + hi) // 2, banda=ev_banda, conf="institucion",
                 ev="institucion: @%s post %s (banda %s)" % (ev_semilla, ev_sc, ev_banda))

    # 3) Sin edad todavia: candidata a la etapa de captions.
    if res["edad_estimada"] and aceptar_baja and ie.EDAD_MIN <= res["edad_estimada"] <= ie.EDAD_MAX:
        return R("aprobado_bio", "aprobado: bio con confianza baja", edad=res["edad_estimada"],
                 banda=ie.banda_de(res["edad_estimada"]), conf="baja", ev="bio: %s" % res["evidencia"])
    return R("pendiente_captions", "sin edad legible en la bio")


def migrar_y_reevaluar(hechos, env, evid, aceptar_baja, log=print):
    """Dos cosas sobre un checkpoint viejo, sin recargar ninguna pagina:

    1. Migra el formato anterior (aprobado si/no) al de tres veredictos.
    2. Re-evalua con la evidencia NUEVA de la cosecha: un perfil que quedo
       "sin edad legible" y ahora aparece etiquetado por una escuela puede
       pasar a aprobado_institucion con los datos que ya se guardaron
       (estado, seguidores, posts, bio)."""
    cambiados = 0
    for u, x in hechos.items():
        if "veredicto" not in x:
            if x.get("aprobado") == "si":
                x["veredicto"], x["banda"], x["evidencia"] = "aprobado_bio", ie.banda_de(int(x["edad_estimada"])) if str(x.get("edad_estimada", "")).isdigit() else "", "bio"
            elif x.get("motivo") == "sin edad legible en la bio":
                x["veredicto"], x["banda"], x["evidencia"] = "pendiente_captions", "", ""
            else:
                x["veredicto"], x["banda"], x["evidencia"] = "rechazado", "", ""
        if x.get("estado_cuenta") == "publica_con_posts" and x["veredicto"] != "rechazado" or (
                x.get("motivo", "").startswith("edad solo con confianza")):
            ev = evid.get(u.lower())
            if True:
                datos = {"estado_cuenta": x.get("estado_cuenta"), "biografia": x.get("biografia", ""),
                         "followers": x.get("seguidores", 0), "posts": x.get("posts", 0),
                         "nombre": "", "username": u}
                v = evaluar(datos, env, ev, aceptar_baja)
                if v["veredicto"] != x["veredicto"]:
                    x.update({"veredicto": v["veredicto"], "motivo": v["motivo"],
                              "edad_estimada": v["edad"] or "", "banda": v["banda"],
                              "confianza_edad": v["confianza"], "evidencia": v["evidencia"]})
                    cambiados += 1
    if cambiados:
        log("TRIAJE: %d perfiles re-evaluados con evidencia nueva, sin recargar." % cambiados)
    return hechos


CATEGORIAS_ESCUELA = ("school", "escuela", "preparatoria", "education", "high school")
CATEGORIAS_UNIVERSIDAD = ("college & university", "university", "universidad")


def descubrir_semillas(hechos, log=print):
    """Cuentas rechazadas por la CATEGORIA de Instagram de escuela o
    universidad -> semillas nuevas. Es el descubrimiento de mayor precision:
    lo dice la plataforma, no el nombre."""
    ruta = os.path.join(DIR, "semillas_descubiertas.txt")
    previas = set()
    if os.path.exists(ruta):
        previas = {l.split(",")[0].strip().lower() for l in open(ruta, encoding="utf-8")
                   if l.strip() and not l.startswith("#")}
    try:
        import cosechar_candidatos as cc
        previas |= {s_["valor"].lower() for s_ in cc.SEMILLAS}
    except Exception:
        pass
    nuevas = []
    for u, x in hechos.items():
        m = x.get("motivo", "")
        if not m.startswith("cuenta profesional ("):
            continue
        cat = m[len("cuenta profesional ("):-1]
        if u.lower() in previas:
            continue
        # fuera de Jalisco, fuera
        if any(t in u.lower() for t in ("qro", "queretaro", "cdmx", "monterrey", "puebla", "usach")):
            continue
        if any(c in cat for c in CATEGORIAS_ESCUELA):
            nuevas.append((u, "prepa"))
        elif any(c in cat for c in CATEGORIAS_UNIVERSIDAD):
            nuevas.append((u, "universidad"))
    if nuevas:
        with open(ruta, "a", encoding="utf-8") as f:
            if not os.path.getsize(ruta) if os.path.exists(ruta) else True:
                f.write("# Semillas descubiertas. handle,clase,nota\n")
            for u, clase in nuevas:
                f.write("%s,%s,categoria de Instagram %s\n" % (u, clase, datetime.now().date().isoformat()))
        log("TRIAJE: %d semillas nuevas por categoria de Instagram -> %s" % (len(nuevas), ruta))
    return nuevas


def escribir_salidas(hechos):
    filas = list(hechos.values())
    if not filas:
        return 0, 0
    campos = ["id", "usuario", "veredicto", "motivo", "estado_cuenta", "seguidores", "posts",
              "edad_estimada", "banda", "confianza_edad", "evidencia", "biografia"]
    with open(SALIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows([{k: x.get(k, "") for k in campos} for x in filas])
    hoy = datetime.now().strftime("%m/%d/%Y")

    aprob = [x for x in filas if str(x["veredicto"]).startswith("aprobado")]
    with open(APROBADOS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
        for x in aprob:
            w.writerow([id_control(x["usuario"]), "1/1/2010", hoy, x["usuario"], "", "", ""])

    pend = [x for x in filas if x["veredicto"] == "pendiente_captions"]
    with open(PENDIENTES, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
        for x in pend:
            w.writerow([id_control(x["usuario"], "PEND"), "1/1/2010", hoy, x["usuario"], "", "", ""])
    return len(aprob), len(pend)


def resumen(hechos, log=print):
    from collections import Counter
    filas = list(hechos.values())
    if not filas:
        return
    c = Counter(x["veredicto"] for x in filas)
    log("TRIAJE: %d perfiles | aprobado_bio %d | aprobado_institucion %d | pendiente_captions %d | rechazados %d"
        % (len(filas), c.get("aprobado_bio", 0), c.get("aprobado_institucion", 0),
           c.get("pendiente_captions", 0), c.get("rechazado", 0)))
    top = Counter(x["motivo"].split(" (")[0] for x in filas if x["veredicto"] == "rechazado").most_common(6)
    for m, n in top:
        log("     %-44s %d" % (m, n))


def correr(driver, ig, ruta_csv, limite=10 ** 6, reanudar=True, dormir_al_limite=True,
           aceptar_baja=False, log=print, tope_cargas=None, contador=None):
    """Tria los perfiles pendientes de ruta_csv. Reutilizable desde el orquestador.
    contador: dict compartido {"cargas": n} para el tope diario del orquestador."""
    env = cargar_envolvente()
    evid = cargar_evidencia()
    filas = [r for r in csv.DictReader(open(ruta_csv, encoding="utf-8-sig")) if r.get("instagram")]
    hechos = {}
    if reanudar and os.path.exists(CKPT):
        hechos = json.load(open(CKPT, encoding="utf-8"))
        hechos = migrar_y_reevaluar(hechos, env, evid, aceptar_baja, log)
        json.dump(hechos, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
    pendientes = [r for r in filas if r["instagram"] not in hechos][:limite]
    log("TRIAJE: %d en lista, %d ya hechos, %d por hacer (~%.1f h)"
        % (len(filas), len(hechos), len(pendientes), len(pendientes) * 15 / 3600.0))
    anomalias = 0
    for n, r in enumerate(pendientes, 1):
        if tope_cargas is not None and contador is not None and contador.get("cargas", 0) >= tope_cargas:
            log("TRIAJE: tope de cargas del dia alcanzado, paro aqui.")
            break
        u = r["instagram"]
        try:
            driver.get("https://www.instagram.com/%s/" % u)
            if contador is not None:
                contador["cargas"] = contador.get("cargas", 0) + 1
            time.sleep(ESPERA_CARGA)
            with open(TMP_HTML, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            datos = ig.parsear_html_perfil(TMP_HTML)
            v = evaluar(datos, env, evid.get(u.lower()), aceptar_baja)
            hechos[u] = {
                "id": r.get("id", ""), "usuario": u, "veredicto": v["veredicto"], "motivo": v["motivo"],
                "estado_cuenta": datos.get("estado_cuenta", ""),
                "seguidores": numero(datos.get("followers")), "posts": numero(datos.get("posts")),
                "edad_estimada": v["edad"] or "", "banda": v["banda"], "confianza_edad": v["confianza"],
                "evidencia": v["evidencia"],
                "biografia": (datos.get("biografia") or "").replace("\n", " ")[:200],
            }
            anomalias = 0 if datos.get("estado_cuenta") else anomalias + 1
            marca = {"aprobado_bio": "OK-bio ", "aprobado_institucion": "OK-inst",
                     "pendiente_captions": "PEND   "}.get(v["veredicto"], "       ")
            log("  [%d/%d] %s %-28s %s" % (n, len(pendientes), marca, u, v["motivo"]))
        except Exception as e:
            log("  [%d/%d]         %-28s ERROR: %s" % (n, len(pendientes), u, e))
            hechos[u] = {"id": r.get("id", ""), "usuario": u, "veredicto": "rechazado",
                         "motivo": "error: %s" % str(e)[:80], "estado_cuenta": "", "seguidores": 0,
                         "posts": 0, "edad_estimada": "", "banda": "", "confianza_edad": "",
                         "evidencia": "", "biografia": ""}
            anomalias += 1
        json.dump(hechos, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
        if anomalias >= LIMITE_ANOMALIAS:
            if dormir_al_limite:
                log("  *** %d perfiles seguidos ilegibles: huele a limite. Duermo %d min y sigo."
                    % (anomalias, SIESTA_LIMITE_S // 60))
                time.sleep(SIESTA_LIMITE_S)
                anomalias = 0
                # Los ultimos 8 se marcaron con error; se reintentan al reanudar.
                for x in list(hechos.values())[-LIMITE_ANOMALIAS:]:
                    if x["motivo"].startswith("error") or not x["estado_cuenta"]:
                        hechos.pop(x["usuario"], None)
                json.dump(hechos, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
            else:
                log("  *** %d perfiles seguidos ilegibles. Corto. Vuelve con --reanudar." % anomalias)
                break
        time.sleep(random.uniform(*PAUSA))
    if os.path.exists(TMP_HTML):
        try:
            os.remove(TMP_HTML)
        except OSError:
            pass
    n_ap, n_pe = escribir_salidas(hechos)
    descubrir_semillas(hechos, log)
    resumen(hechos, log)
    log("TRIAJE: -> %s (%d aprobados), %s (%d pendientes)" % (APROBADOS, n_ap, PENDIENTES, n_pe))
    return hechos


def main():
    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d
    ruta_csv = arg("--csv", os.path.join(DIR, "candidatos_formato.csv"))
    if not os.path.exists(ruta_csv):
        sys.exit("No encuentro %s" % ruta_csv)
    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait
    import scrappingData_ig as ig
    driver = webdriver.Chrome()
    try:
        ig.iniciar_sesion(driver, WebDriverWait(driver, ig.ESPERA_LOGIN))
        correr(driver, ig, ruta_csv, limite=int(arg("--limite", 10 ** 6)),
               reanudar="--reanudar" in sys.argv, dormir_al_limite="--dormir-al-limite" in sys.argv,
               aceptar_baja="--aceptar-baja" in sys.argv)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
