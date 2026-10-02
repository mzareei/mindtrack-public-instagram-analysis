# -*- coding: utf-8 -*-
"""
Emparejamiento de controles y tabla de balance.

Toma los candidatos ya raspados, aplica la envolvente derivada de los pacientes,
empareja por estratos y produce la tabla de balance que va en el articulo.

Orden de las operaciones, y por que ese orden:

  1. FILTRO DURO. Cuenta publica con posts; edad inferida 15-29 con confianza
     alta o media; dentro de la envolvente de seguidores, posts y ritmo; y que
     NO este en la red de ningun paciente (ver exclusiones.py).
  2. ESTRATOS. Emparejamiento exacto grueso sobre banda de edad x estrato de
     seguidores x estrato de actividad. Exacto grueso antes que puntaje de
     propension porque con n=30 casos un puntaje solo se sobreajusta y deja
     desbalances feos en las variables que mas importan.
  3. VECINO MAS CERCANO dentro del estrato, sobre el puntaje de propension de
     metadatos, sin reemplazo, razon configurable (2:1 por defecto).
  4. TABLA DE BALANCE con diferencia de medias estandarizada (DME) antes y
     despues. Criterio: |DME| < 0.10 se considera balanceado; 0.10-0.25 hay que
     mencionarlo; > 0.25 el emparejamiento no sirve para esa variable.

Despues de esto SIEMPRE hay que correr detector_marco.py sobre el resultado. La
tabla de balance dice si las variables que miraste quedaron parejas; el detector
dice si algo que no miraste sigue delatando el reclutamiento.

Uso (una sola linea; en PowerShell el "\\" de continuacion no funciona,
el separador ahi es el acento grave):

    python ig/control/emparejar.py --casos resultados_ig/global_20260828_163758.json --controles resultados_ig/global_controles_unido_20260907_211554.json --razon 2 --relajar

    --casos F        global de pacientes. OBLIGATORIO en la practica: casos y
                     controles tienen que salir del mismo tipo de fichero, o el
                     puntaje de propension acaba separando formatos, no personas.
    --controles F    global de controles ya unido (unir_globals.py --todos).
    --caliper N      años de tolerancia para edad puntual de bio/captions
                     (2 por defecto). La evidencia institucional usa su banda
                     y no se ve afectada.

    --razon N        cuantos controles por caso (2 por defecto)
    --aceptar-baja   admite tambien edades inferidas con confianza baja
                     (nivel escolar o generacion). Sube la cobertura y baja la
                     precision; hay que decirlo en el articulo.
    --relajar        si un estrato se queda vacio, busca en estratos vecinos.
                     La banda de edad nunca se relaja. Los controles asi
                     obtenidos quedan marcados en el CSV.
"""

import csv, json, math, os, re, sys, statistics as st
from datetime import datetime
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inferir_edad as ie
import detector_marco as dm
from exclusiones import cargar_exclusiones, _norm
from util import numero, categoria_profesional, ruta_dataset, es_no_persona


def _ruta(*p):
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, *p)


def cargar_envolvente():
    ruta = _ruta("ig", "control", "envolvente_control.json")
    if not os.path.exists(ruta):
        sys.exit("Falta envolvente_control.json. Corre antes:\n"
                 "   python ig/control/envolvente.py")
    return json.load(open(ruta, encoding="utf-8"))


def perfiles_pacientes():
    """Reconstruye los perfiles de pacientes desde los CSV de extraccion, en el
    mismo formato que un registro del scraper, para poder compararlos."""
    perf = {r["id"]: r for r in csv.DictReader(
        open(_ruta("resultados_ig", "extraccion", "perfiles.csv"), encoding="utf-8-sig"))
        if r["estado_cuenta"] == "publica_con_posts"}
    posts = defaultdict(list)
    for p in csv.DictReader(open(_ruta("resultados_ig", "extraccion", "posts.csv"),
                                 encoding="utf-8-sig")):
        if p["es_del_perfil"] == "si":
            posts[p["id"]].append({"fecha": p["fecha"], "tipo_media": p["tipo_media"],
                                   "caption": p["caption"], "hashtags": p["hashtags"],
                                   "ubicacion": p["ubicacion"], "es_del_perfil": True})
    salida = []
    for pid, r in perf.items():
        salida.append({
            "id": pid, "usuario": r["usuario"], "biografia": r["biografia"],
            "nombre": r["nombre"], "estado_cuenta": r["estado_cuenta"],
            # numero(), no isdigit(): "1,180" y "158K" no son digitos y se
            # convertian en None -> 0 seguidores para pacientes que si tienen.
            "followers": numero(r["followers"]),
            "following": numero(r["following"]),
            "posts_data": posts.get(pid, []),
        })
    return salida


def resumen(perfil):
    posts = [p for p in (perfil.get("posts_data") or [])
             if p.get("es_del_perfil", True) in (True, "si", "True")]
    fechas = sorted(datetime.fromisoformat(str(p["fecha"])) for p in posts if p.get("fecha"))
    # Piso de 3 meses: una cuenta con 3 posts en una semana NO publica "12 al
    # mes". Sin el piso, las cuentas chicas (que son justo las que buscamos)
    # salian con ritmos absurdos y se caian de la envolvente.
    meses = max(3.0, (fechas[-1] - fechas[0]).days / 30.44) if len(fechas) > 1 else 3.0
    return {
        "n_posts": len(posts),
        "tasa_mes": len(posts) / meses,
        "primer_post": fechas[0].date().isoformat() if fechas else "",
        "ultimo_post": fechas[-1].date().isoformat() if fechas else "",
        # followers/following llegan como texto de Instagram ("1,180", "158K").
        "seguidores": numero(perfil.get("followers")),
        "siguiendo": numero(perfil.get("following")),
    }


def estrato(valor, cortes):
    for i, c in enumerate(cortes):
        if valor <= c:
            return i
    return len(cortes)


def descartes_manuales():
    """Handles tirados a mano tras revisar la evidencia de edad, con su motivo.

    La revision de `controles_evidencia.csv` encontro dos casos en los que el
    numero que el inferidor leyo como edad no era una edad: años de competicion
    deportiva ('’24) y un parametro de URL (s=21). Un patron automatico no los
    distingue del '24' de alguien que dice tener 24, asi que se listan a mano.
    """
    ruta = _ruta("ig", "control", "descartes_manuales.txt")
    fuera = {}
    if not os.path.exists(ruta):
        return fuera
    for linea in open(ruta, encoding="utf-8"):
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        handle, _, motivo = linea.partition("#")
        handle = handle.strip().lower()
        if handle:
            fuera[handle] = motivo.strip()
    return fuera


def dme(a, b):
    """Diferencia de medias estandarizada."""
    if not a or not b:
        return float("nan")
    ma, mb = st.mean(a), st.mean(b)
    va = st.pvariance(a) if len(a) > 1 else 0.0
    vb = st.pvariance(b) if len(b) > 1 else 0.0
    den = math.sqrt((va + vb) / 2.0)
    return (ma - mb) / den if den else 0.0


# El tercer campo marca las variables con cola larga a la derecha (conteos de
# Instagram). En esas, la DME sobre la escala cruda la domina un punado de
# cuentas grandes: un solo paciente con 57,300 seguidores mueve la media del
# grupo de 421 a 1,419. La practica estandar para conteos sesgados es evaluar
# el balance en log1p, que ademas es la escala en la que emparejamos. Se
# reportan las dos: 'dme' (primaria, log en las sesgadas) y 'dme_cruda'.
VARIABLES_BALANCE = [
    ("edad", lambda p, r, e: e or 0, False),
    ("seguidores", lambda p, r, e: r["seguidores"], True),
    ("siguiendo", lambda p, r, e: r["siguiendo"], True),
    ("n_posts", lambda p, r, e: r["n_posts"], True),
    ("tasa_posts_mes", lambda p, r, e: r["tasa_mes"], True),
    ("tiene_bio", lambda p, r, e: 1 if (p.get("biografia") or "").strip() else 0, False),
]


def tabla_balance(casos, controles, edades, titulo):
    print("\n%s" % titulo)
    print("%-16s %9s %9s %9s %9s %8s %8s  %s" % (
        "variable", "med.casos", "med.ctrl", "mna.casos", "mna.ctrl",
        "DME", "DMEcruda", "veredicto"))
    print("-" * 92)
    filas = []
    for nombre, f, sesgada in VARIABLES_BALANCE:
        a = [f(p, resumen(p), edades.get(id(p))) for p in casos]
        b = [f(p, resumen(p), edades.get(id(p))) for p in controles]
        d_cruda = dme(a, b)
        if sesgada:
            d = dme([math.log1p(max(0.0, x)) for x in a],
                    [math.log1p(max(0.0, x)) for x in b])
        else:
            d = d_cruda
        v = ("balanceado" if abs(d) < 0.10 else
             "mencionar" if abs(d) < 0.25 else "NO BALANCEADO")
        print("%-16s %9.1f %9.1f %9.1f %9.1f %8.3f %8.3f  %s" % (
            nombre, st.median(a), st.median(b), st.mean(a), st.mean(b),
            d, d_cruda, v))
        filas.append({"variable": nombre,
                      "mediana_casos": round(st.median(a), 2),
                      "mediana_controles": round(st.median(b), 2),
                      "media_casos": round(st.mean(a), 2),
                      "media_controles": round(st.mean(b), 2),
                      "escala_dme": "log1p" if sesgada else "cruda",
                      "dme": round(d, 3),
                      "dme_cruda": round(d_cruda, 3),
                      "veredicto": v})
    if any(x["escala_dme"] == "log1p" for x in filas):
        print("  DME de conteos calculada en log1p (escala del emparejamiento);")
        print("  'DMEcruda' se reporta al lado porque la cola derecha la infla.")
    return filas


def main():
    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d

    ruta_ctrl = arg("--controles")
    # Caliper de edad para evidencia puntual (bio/captions): +/- N años.
    # 2 por defecto. 3 es defendible en el estrato 26-29, donde no hay
    # candidatos y un año de diferencia a esa edad no cambia nada; hay que
    # declararlo en el articulo si se usa.
    caliper = int(arg("--caliper", 2))
    if not ruta_ctrl:
        sys.exit(__doc__)
    # Los casos deben venir del MISMO tipo de fichero que los controles.
    # DEFECTO 10 (07/09/2026): se reconstruian desde los CSV de extraccion
    # mientras los controles salian del global crudo. Los dos formatos nombran
    # los campos distinto, asi que el puntaje de propension separaba FORMATOS,
    # no personas, y el emparejamiento salia practicamente al azar.
    ruta_casos = arg("--casos")
    razon = int(arg("--razon", 2))
    aceptar_baja = "--aceptar-baja" in sys.argv

    env = cargar_envolvente()
    fuera = cargar_exclusiones()
    casos = dm.cargar_global(ruta_casos) if ruta_casos else perfiles_pacientes()
    if not ruta_casos:
        print("  AVISO: sin --casos se reconstruyen desde los CSV y el puntaje de")
        print("         propension compara formatos distintos. Pasa --casos <global_pacientes>.")
    crudos = dm.cargar_global(ruta_ctrl)

    print("\nEMPAREJAMIENTO DE CONTROLES   (caliper de edad +/-%d para bio/captions)" % caliper)
    print("  casos (pacientes publicos con posts) : %d" % len(casos))
    print("  candidatos raspados                  : %d" % len(crudos))
    print("  handles en la red de pacientes       : %d (excluidos de entrada)" % len(fuera))

    lim_seg = env["seguidores"]["limite_admision"]
    lim_pos = env["posts_totales"]["limite_admision"]
    lim_tas = env["tasa_posts_mes"]["limite_admision"]

    # La fuente de verdad de QUIEN es control y con QUE edad es
    # controles_evidencia.csv (triaje + captions). Aqui no se vuelve a inferir
    # nada: un control aprobado por evidencia institucional no tiene edad en la
    # bio y se caeria.
    ruta_ev = _ruta("ig", "control", "controles_evidencia.csv")
    evidencia = {}
    if os.path.exists(ruta_ev):
        evidencia = {r["usuario"].lower(): r for r in csv.DictReader(open(ruta_ev, encoding="utf-8-sig"))}
    if not evidencia:
        sys.exit("Falta controles_evidencia.csv. Corre antes triaje.py o reevaluar.py.")
    print("  controles con evidencia               : %d" % len(evidencia))

    manuales = descartes_manuales()
    if manuales:
        print("  descartados a mano por evidencia mala  : %d (%s)"
              % (len(manuales), ", ".join(sorted(manuales))))

    edades, admitidos, descartes = {}, [], Counter()
    for r in crudos:
        u = (r.get("usuario") or "").lower()
        if u in manuales:
            descartes["descartado a mano (evidencia de edad falsa)"] += 1
            continue
        if _norm(r.get("usuario")) in fuera:
            descartes["en la red de un paciente"] += 1
            continue
        ev = evidencia.get(u)
        if not ev:
            descartes["no esta en controles_evidencia.csv (no aprobado)"] += 1
            continue
        cat = categoria_profesional(r.get("biografia", ""))
        if cat and "--incluir-profesionales" not in sys.argv:
            descartes["cuenta profesional (%s)" % cat.lower()] += 1
            continue
        # 9/9/2026: la evidencia institucional dejaba entrar bandas, posgrados,
        # marcas y medicos en ejercicio a los que una escuela etiqueta. Ver
        # util.es_no_persona.
        np_ = es_no_persona(r.get("nombre"), r.get("biografia"), r.get("posts_data"), u)
        if np_:
            descartes["no es una persona: " + np_.split(" (")[0]] += 1
            continue
        try:
            edad_ev = int(float(ev.get("edad_estimada") or 0)) or None
        except ValueError:
            edad_ev = None
        if not edad_ev:
            descartes["sin edad en la evidencia"] += 1
            continue
        res_edad = {"edad_estimada": edad_ev, "confianza": ev.get("confianza", ""),
                    "evidencia": "%s: %s" % (ev.get("tipo_evidencia", ""), ev.get("evidencia", ""))}
        # Rango de edad que la evidencia SOSTIENE. Una etiqueta de la FEU dice
        # "15-24", no "19": ese control es elegible para cualquier caso de 15 a
        # 24, no solo para los de 18-21. Una edad puntual de bio o caption vale
        # +/-2 años. Esto es lo que hace usable la evidencia institucional para
        # los casos de 22-25, que son la mayoria de los pacientes.
        banda_ev = ev.get("banda", "")
        m_b = re.match(r"^(\d{2})-(\d{2})$", banda_ev or "")
        if ev.get("tipo_evidencia") == "institucion" and m_b:
            r["_edad_lo"], r["_edad_hi"] = int(m_b.group(1)), int(m_b.group(2))
        else:
            r["_edad_lo"], r["_edad_hi"] = edad_ev - caliper, edad_ev + caliper
        r["_tipo_evidencia"] = ev.get("tipo_evidencia", "")
        s = resumen(r)
        if not (lim_seg[0] <= s["seguidores"] <= lim_seg[1]):
            descartes["seguidores fuera de la envolvente"] += 1
            continue
        if not (lim_pos[0] <= s["n_posts"] <= lim_pos[1]):
            descartes["numero de posts fuera de la envolvente"] += 1
            continue
        if not (lim_tas[0] <= s["tasa_mes"] <= lim_tas[1]):
            descartes["ritmo de publicacion fuera de la envolvente"] += 1
            continue
        edades[id(r)] = res_edad["edad_estimada"]
        r["_edad_inferida"] = res_edad["edad_estimada"]
        r["_confianza_edad"] = res_edad["confianza"]
        r["_evidencia_edad"] = res_edad["evidencia"]
        admitidos.append(r)

    print("\n  Embudo:")
    for motivo, n in descartes.most_common():
        print("    -%-46s %d" % (motivo, n))
    print("    = admitidos%36s %d" % ("", len(admitidos)))
    if not admitidos:
        sys.exit("\nNingun candidato pasa el filtro. Revisa la siembra.")

    # Edad de los casos desde el dataset clinico.
    ruta_ds = ruta_dataset()
    if not ruta_ds:
        sys.exit("\nNo encuentro mindtrack_dataset_v1.csv (edades de los casos). Sin el no se\n"
                 "puede emparejar a nadie. Pon en .env una linea\n"
                 "    MINDTRACK_DATASET=C:\\ruta\\completa\\a\\mindtrack_dataset_v1.csv\n"
                 "o copia el fichero a la raiz del repo.")
    print("  dataset clinico                       : %s" % ruta_ds)
    ds = {r["ID"]: r for r in csv.DictReader(open(ruta_ds, encoding="utf-8-sig"))}
    for p in casos:
        e = ds.get(str(p.get("id")), {}).get("edad", "")
        edades[id(p)] = int(e) if str(e).isdigit() else None

    tabla_balance(casos, admitidos, edades, "BALANCE ANTES DE EMPAREJAR")

    # Estratos de forma de cuenta, con cortes derivados de los casos.
    seg_casos = sorted(resumen(p)["seguidores"] for p in casos)
    tas_casos = sorted(resumen(p)["tasa_mes"] for p in casos)
    cortes_seg = [seg_casos[len(seg_casos) // 3], seg_casos[2 * len(seg_casos) // 3]]
    cortes_tas = [tas_casos[len(tas_casos) // 3], tas_casos[2 * len(tas_casos) // 3]]

    def forma(p):
        r = resumen(p)
        return (estrato(r["seguidores"], cortes_seg), estrato(r["tasa_mes"], cortes_tas))

    def elegible_por_edad(c, edad_caso):
        return edad_caso is not None and c["_edad_lo"] <= edad_caso <= c["_edad_hi"]

    # Puntaje de propension de metadatos para elegir dentro del estrato.
    X = [dm.caracteristicas(p) for p in casos + admitidos]
    y = [1] * len(casos) + [0] * len(admitidos)
    Xs, mu, sd = dm._estandarizar(X)
    w, b = dm.entrenar(Xs, y)
    ps = dm.predecir(Xs, w, b)
    punt = {id(p): ps[i] for i, p in enumerate(casos + admitidos)}

    relajar = "--relajar" in sys.argv
    libres = list(admitidos)
    emparejados, sin_pareja, relajados = [], [], 0
    # Los casos con menos controles elegibles eligen primero, para que los
    # controles versatiles (banda ancha) no se los lleven los casos faciles.
    orden_casos = sorted(casos, key=lambda p: sum(1 for c in libres if elegible_por_edad(c, edades.get(id(p)))))
    for caso in orden_casos:
        edad_c = edades.get(id(caso))
        f_c = forma(caso)
        pool = [c for c in libres if elegible_por_edad(c, edad_c)]
        exactos = sorted([c for c in pool if forma(c) == f_c],
                         key=lambda c: abs(punt[id(c)] - punt[id(caso)]))
        elegidos = [(c, False) for c in exactos[:razon]]
        if len(elegidos) < razon and relajar:
            vecinos = sorted([c for c in pool if forma(c) != f_c
                              and abs(forma(c)[0] - f_c[0]) + abs(forma(c)[1] - f_c[1]) <= 2],
                             key=lambda c: (abs(forma(c)[0] - f_c[0]) + abs(forma(c)[1] - f_c[1]),
                                            abs(punt[id(c)] - punt[id(caso)])))
            for c in vecinos[:razon - len(elegidos)]:
                elegidos.append((c, True))
                relajados += 1
        if len(elegidos) < razon:
            sin_pareja.append((caso["id"], (ie.banda_de(edad_c or 0),) + f_c, len(elegidos)))
        for c, fue_relajado in elegidos:
            libres.remove(c)
            c["_estrato_relajado"] = "si" if fue_relajado else "no"
            emparejados.append((caso["id"], c))

    print("\n  Emparejados: %d controles para %d casos (razon pedida %d:1)"
          % (len(emparejados), len(casos), razon))
    if relajar:
        print("  De ellos, %d salieron de un estrato vecino (--relajar). Van marcados"
              % relajados)
        print("  en el CSV; hay que reportarlos como limitacion.")
    if sin_pareja:
        print("  Casos sin pareja completa: %d" % len(sin_pareja))
        for cid, k, n in sin_pareja[:12]:
            print("    %-10s estrato %s -> solo %d" % (cid, k, n))
        print("  -> hay que sembrar mas en esos estratos, no bajar el criterio.")

    ctrl_final = [c for _, c in emparejados]
    filas_balance = tabla_balance(casos, ctrl_final, edades, "BALANCE DESPUES DE EMPAREJAR")

    salida = _ruta("ig", "control", "controles_emparejados.csv")
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w_ = csv.writer(f)
        w_.writerow(["id_control", "id_caso_pareja", "usuario", "edad_inferida",
                     "confianza_edad", "evidencia_edad", "seguidores", "siguiendo",
                     "n_posts", "tasa_posts_mes", "primer_post", "ultimo_post",
                     "estrato_relajado", "tipo_evidencia", "rango_edad_evidencia"])
        for n, (cid, c) in enumerate(emparejados, 1):
            r = resumen(c)
            w_.writerow(["CTRL%04d" % n, cid, c.get("usuario", ""),
                         c.get("_edad_inferida", ""), c.get("_confianza_edad", ""),
                         c.get("_evidencia_edad", ""), r["seguidores"], r["siguiendo"],
                         r["n_posts"], round(r["tasa_mes"], 2), r["primer_post"],
                         r["ultimo_post"], c.get("_estrato_relajado", "no"),
                         c.get("_tipo_evidencia", ""), "%s-%s" % (c.get("_edad_lo", ""), c.get("_edad_hi", ""))])

    ruta_bal = _ruta("ig", "control", "tabla_balance.csv")
    with open(ruta_bal, "w", newline="", encoding="utf-8-sig") as f:
        w_ = csv.DictWriter(f, fieldnames=list(filas_balance[0].keys()))
        w_.writeheader()
        w_.writerows(filas_balance)

    print("\n  -> %s" % salida)
    print("  -> %s" % ruta_bal)
    print("\n  SIGUIENTE PASO OBLIGATORIO. Copia esta linea entera, tal cual:")
    print("")
    print("python ig/control/detector_marco.py --casos %s --controles %s"
          % (ruta_casos or "resultados_ig/global_PACIENTES.json", ruta_ctrl))
    print("")
    print("     (una sola linea: en PowerShell el '\\' de continuacion no sirve)")
    print("     La tabla de balance solo cubre lo que miraste. El detector cubre")
    print("     lo que no miraste.\n")


if __name__ == "__main__":
    main()
