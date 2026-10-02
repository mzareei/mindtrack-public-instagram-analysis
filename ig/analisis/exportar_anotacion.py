# -*- coding: utf-8 -*-
"""
Exporta el corpus del diseño intrasujeto listo para anotar, y CIEGO.

Que produce:

  anotacion/corpus_anotacion.csv   lo que ve quien anota: un codigo opaco y el
                                   texto. Nada mas.
  anotacion/clave_anotacion.csv    el mapa codigo -> paciente, ventana, fecha.
                                   ESTE FICHERO NO SE ENTREGA A QUIEN ANOTA.

Por que ciego, y por que importa mas aqui que de costumbre. La hipotesis es que
el lenguaje cambia cerca del episodio. Si quien anota sabe que un post es de la
ventana pericrisis, va a codificar "desesperanza" con el pulgar en la balanza, y
el contraste se vuelve circular: mediria la expectativa del anotador, no el
texto. Por eso el fichero de anotacion no lleva ni ventana, ni fecha, ni ID de
paciente, y las filas van barajadas con semilla fija (reproducible).

La fecha se omite del todo: con la fecha y el calendario de reclutamiento se
puede reconstruir la ventana, asi que publicarla al anotador rompe el ciego por
la puerta de atras.

Seleccion. Para cada paciente discordante (con posts en las dos ventanas) se
toman hasta --tope posts por ventana. Si hay mas, se muestrean al azar con
semilla fija, NO se cogen los mas cercanos al episodio: eso concentraria la
ventana pericrisis en los dias del ingreso y exageraria cualquier efecto.

Los posts sin caption se exportan igual, marcados, porque su ausencia de texto
es un dato del diseño (dejar de escribir es una conducta); pero se cuentan
aparte para que el presupuesto real de anotacion no se infle.

Uso:
    python ig/analisis/exportar_anotacion.py [--ventana 90] [--tope 20] [--semilla 20260907]
"""

import csv, os, random, shutil, sys
import datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ventanas_temporales import (_ruta, FIN_OBSERVACION, DIAS_BASELINE)


def cargar_todo():
    sys.path.insert(0, _ruta("ig", "control"))
    from util import ruta_dataset
    c = ruta_dataset()
    if not c:
        sys.exit("No encuentro mindtrack_dataset_v1.csv. Pon MINDTRACK_DATASET=<ruta> en .env.")
    ds = {r["ID"]: r for r in csv.DictReader(open(c, encoding="utf-8-sig"))}
    posts = defaultdict(list)
    for p in csv.DictReader(open(_ruta("resultados_ig", "extraccion", "posts.csv"),
                                 encoding="utf-8-sig")):
        if p.get("es_del_perfil") != "si":
            continue
        try:
            f = dt.date.fromisoformat(p["fecha"][:10])
        except (ValueError, KeyError):
            continue
        posts[p["id"]].append({
            "fecha": f, "shortcode": p.get("shortcode", ""),
            "caption": (p.get("caption") or "").strip(),
            "imagen": (p.get("imagen_local") or "").strip(),
            "video": (p.get("video_local") or "").strip(),
            "palabras": int(p.get("palabras_caption") or 0),
            "tipo": p.get("tipo_media", ""),
        })
    return ds, posts


def main():
    def arg(n, d):
        return int(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d
    VENT, TOPE, SEM = arg("--ventana", 90), arg("--tope", 20), arg("--semilla", 20260907)
    rnd = random.Random(SEM)

    ds, posts = cargar_todo()
    seleccion = []
    resumen = []

    for pid in sorted(posts):
        row = ds.get(pid)
        if not row or not row.get("fecha_consentimiento"):
            continue
        fc = dt.date.fromisoformat(row["fecha_consentimiento"])
        ps = posts[pid]
        inicio = min(p["fecha"] for p in ps)

        p0, p1 = fc - dt.timedelta(VENT), min(fc + dt.timedelta(VENT), FIN_OBSERVACION)
        b1, b0 = p0, max(fc - dt.timedelta(VENT + DIAS_BASELINE), inicio)

        peri = [p for p in ps if p0 <= p["fecha"] <= p1]
        base = [p for p in ps if b0 <= p["fecha"] <= b1]
        if not (peri and base):
            continue

        for etiqueta, grupo in (("peri", peri), ("base", base)):
            elegidos = grupo if len(grupo) <= TOPE else rnd.sample(grupo, TOPE)
            for p in elegidos:
                seleccion.append({**p, "id_paciente": pid, "ventana": etiqueta})
        resumen.append((pid, len(peri), len(base),
                        min(len(peri), TOPE), min(len(base), TOPE)))

    rnd.shuffle(seleccion)
    for i, s in enumerate(seleccion, 1):
        s["codigo"] = "P%04d" % i

    con_texto = [s for s in seleccion if s["caption"]]
    sin_texto = [s for s in seleccion if not s["caption"]]

    dirsal = _ruta("anotacion")
    os.makedirs(dirsal, exist_ok=True)

    # Las imagenes se copian con el nombre opaco. La ruta original lleva el
    # usuario dentro (media/<usuario>/<shortcode>.jpg), asi que entregarla tal
    # cual rompe el anonimato y el ciego a la vez.
    dirimg = os.path.join(dirsal, "img")
    os.makedirs(dirimg, exist_ok=True)
    copiadas = 0
    for s_ in seleccion:
        s_["archivo"] = ""
        origen = _ruta("resultados_ig", s_["imagen"]) if s_["imagen"] else ""
        if origen and os.path.exists(origen):
            destino = os.path.join(dirimg, s_["codigo"] + ".jpg")
            if not os.path.exists(destino):
                shutil.copyfile(origen, destino)
            s_["archivo"] = "img/" + s_["codigo"] + ".jpg"
            copiadas += 1

    ruta_corpus = os.path.join(dirsal, "corpus_anotacion.csv")
    with open(ruta_corpus, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "tiene_texto", "imagen", "texto",
                    "expresion_simbolica", "desesperanza", "carga_percibida",
                    "pertenencia", "dolor_psiquico", "atrapamiento",
                    "orientacion_temporal", "busqueda_de_apoyo", "despedida",
                    "confianza_anotador", "notas"])
        for s in seleccion:
            w.writerow([s["codigo"], "si" if s["caption"] else "no",
                        s["archivo"], s["caption"]] + [""] * 11)

    ruta_clave = os.path.join(dirsal, "clave_anotacion.csv")
    with open(ruta_clave, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "id_paciente", "ventana", "fecha", "shortcode",
                    "tipo_media", "palabras"])
        for s in seleccion:
            w.writerow([s["codigo"], s["id_paciente"], s["ventana"],
                        s["fecha"].isoformat(), s["shortcode"], s["tipo"],
                        s["palabras"]])

    print("\nCORPUS DE ANOTACION  (ciego, ventana +/-%d d, tope %d/ventana)" % (VENT, TOPE))
    print("=" * 66)
    print("  pacientes discordantes      : %d" % len(resumen))
    print("  posts exportados            : %d" % len(seleccion))
    print("     con caption (a anotar)   : %d" % len(con_texto))
    print("     sin caption (solo imagen): %d" % len(sin_texto))
    n_peri = sum(1 for s in seleccion if s["ventana"] == "peri")
    print("  reparto peri / base         : %d / %d" % (n_peri, len(seleccion) - n_peri))
    pal = sum(s["palabras"] for s in con_texto)
    print("  palabras a leer             : %d (mediana %d por post)"
          % (pal, sorted(s["palabras"] for s in con_texto)[len(con_texto) // 2]))
    print()
    print("  imagenes copiadas con nombre opaco: %d" % copiadas)
    print()
    print("  -> %s" % ruta_corpus)
    print("  -> %s/" % dirimg)
    print("  -> %s   NO ENTREGAR A QUIEN ANOTA" % ruta_clave)
    print()
    print("  Comprobacion del ciego: el corpus no lleva fecha, ni ventana, ni ID de")
    print("  paciente, y va barajado con semilla %d." % SEM)
    print()


if __name__ == "__main__":
    main()
