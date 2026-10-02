# -*- coding: utf-8 -*-
"""
Convierte el global_*.json en CSV planos, listos para pandas.

Genera en resultados_ig/extraccion/:
    perfiles.csv    un renglon por perfil
    posts.csv       un renglon por post
    comentarios.csv un renglon por comentario

Los campos que el scraper ya trae (estado_cuenta, biografia, autor_post,
es_del_perfil, media_local, video_local) salen del JSON. Los que solo viven en
el HTML del post (geoetiqueta, audio, tipo de media, alt generado por Meta) se
leen de resultados_ig/debug_dom si esta disponible.

Para quedarte solo con texto del paciente:
    posts.csv       -> es_del_perfil == "si"
    comentarios.csv -> post_es_del_perfil == "si"

Uso:
    python ig/exportar_csv.py
    python ig/exportar_csv.py resultados_ig/global_20260828_163758.json
"""
import os, re, sys, csv, json, glob, html as H

RESULTADOS_DIR = "resultados_ig"
SALIDA = os.path.join(RESULTADOS_DIR, "extraccion")


def sin_scripts(s):
    return re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)


def indice_dom():
    """shortcode -> ruta del HTML del post."""
    idx = {}
    for f in glob.glob(os.path.join(RESULTADOS_DIR, "debug_dom", "*.html")):
        base = os.path.basename(f)[:-5]
        # los nombres son <shortcode>_AAAAMMDD_HHMMSS o <shortcode>_HHMMSS
        sc = re.sub(r"_\d{8}_\d{6}$|_\d{6}$", "", base)
        idx.setdefault(sc, f)
    return idx


def datos_del_html(ruta):
    """Lo que solo esta en el DOM del post."""
    if not ruta or not os.path.exists(ruta):
        return {}
    crudo = open(ruta, encoding="utf-8", errors="ignore").read()
    b = sin_scripts(crudo)
    loc = re.findall(r'href="/explore/locations/\d+/([^"/]+)/?"', b)
    alt = [H.unescape(a) for a in re.findall(r'alt="([^"]{12,400})"', b)
           if re.match(r"Photo by .+ on .+\. May be an image", a)]
    return {
        "tipo_media": ("video/reel" if re.search(r"<video[\s>]", b)
                       else "carrusel" if re.search(r'aria-label="(Next|Go to slide|Siguiente)', b)
                       else "imagen"),
        "ubicacion": loc[0] if loc else "",
        "audio": "si" if re.search(r'href="/reels/audio/', b) else "",
        "alt_meta_imagen": alt[0][:200] if alt else "",
    }


def main():
    libres = [a for a in sys.argv[1:] if not a.startswith("-")]
    if libres:
        ruta = libres[0]
    else:
        cand = [f for f in glob.glob(os.path.join(RESULTADOS_DIR, "global_2*.json"))
                if "anonimo" not in os.path.basename(f)]
        if not cand:
            sys.exit("No encuentro ningun global_*.json en %s" % RESULTADOS_DIR)
        ruta = sorted(cand)[-1]

    print("Leyendo: %s" % ruta)
    datos = json.load(open(ruta, encoding="utf-8")).get("resultados", [])
    dom = indice_dom()
    print("HTML de post disponibles: %d\n" % len(dom))
    os.makedirs(SALIDA, exist_ok=True)

    pat_meta = re.compile(r"^([\d,]+)\s+likes?,\s+([\d,]+)\s+comments?", re.I)
    perfiles, posts, comentarios = [], [], []

    for r in datos:
        usuario = r.get("usuario") or ""
        propios = 0
        for p in (r.get("posts_data") or []):
            sc = re.search(r"/(?:p|reel)/([^/]+)/", p.get("url") or "")
            sc = sc.group(1) if sc else ""
            m = pat_meta.match((p.get("caption_raw") or "").strip())
            cap = p.get("caption") or ""
            del_perfil = "si" if p.get("es_del_perfil", True) else "no"
            if del_perfil == "si":
                propios += 1
            extra = datos_del_html(dom.get(sc))
            posts.append({
                "id": r.get("id"), "usuario": usuario, "shortcode": sc,
                "url": p.get("url"), "fecha": p.get("fecha_post_iso") or "",
                "anio": (p.get("fecha_post_iso") or "")[:4],
                "es_del_perfil": del_perfil, "autor_post": p.get("autor_post") or usuario,
                "likes": int(m.group(1).replace(",", "")) if m else "",
                "comentarios_ig": int(m.group(2).replace(",", "")) if m else "",
                "comentarios_extraidos": len(p.get("comments") or []),
                "tipo_media": extra.get("tipo_media", ""),
                "ubicacion": extra.get("ubicacion", ""),
                "audio": extra.get("audio", ""),
                "caption": cap, "palabras_caption": len(cap.split()),
                "hashtags": " ".join(re.findall(r"#\w+", cap)),
                "menciones": " ".join(re.findall(r"@[\w.]+", cap)),
                "alt_meta_imagen": extra.get("alt_meta_imagen", ""),
                "imagen_local": p.get("media_local") or "",
                "video_local": p.get("video_local") or "",
            })
            for c in (p.get("comments") or []):
                autor = (c.get("autor") or "")
                comentarios.append({
                    "id": r.get("id"), "usuario_perfil": usuario, "shortcode": sc,
                    "post_es_del_perfil": del_perfil,
                    "comment_id": c.get("comment_id"), "autor": autor,
                    "es_del_paciente": "si" if autor.lower() == usuario.lower() else "no",
                    "es_reply": c.get("es_reply"), "parent": c.get("parent_comment_id") or "",
                    "texto": c.get("texto") or "",
                    "palabras": len((c.get("texto") or "").split()),
                })
        n = len(r.get("posts_data") or [])
        ig = str(r.get("posts") or "").replace(",", "")
        perfiles.append({
            "id": r.get("id"), "usuario": usuario, "nombre": r.get("nombre") or "",
            "estado_cuenta": r.get("estado_cuenta") or "",
            "biografia": r.get("biografia") or "",
            "followers": r.get("followers") or "", "following": r.get("following") or "",
            "followers_og": r.get("followers_og") or "", "following_og": r.get("following_og") or "",
            "metricas_fuente": r.get("metricas_fuente") or "",
            "posts_ig": r.get("posts") or "", "posts_extraidos": n,
            "posts_propios": propios, "posts_ajenos": n - propios,
            "cobertura_pct": round(100 * n / int(ig), 1) if ig.isdigit() and int(ig) else "",
            "error": r.get("error") or "",
        })

    for nombre, filas in (("perfiles.csv", perfiles), ("posts.csv", posts),
                          ("comentarios.csv", comentarios)):
        if not filas:
            continue
        with open(os.path.join(SALIDA, nombre), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            w.writeheader(); w.writerows(filas)
        print("  %-18s %d filas" % (nombre, len(filas)))

    pal = sum(r["palabras_caption"] for r in posts if r["es_del_perfil"] == "si")
    pc = sum(c["palabras"] for c in comentarios
             if c["post_es_del_perfil"] == "si" and c["es_del_paciente"] == "si")
    print("\nCorpus del paciente: %d posts, %d palabras de caption + %d de comentarios = %d"
          % (sum(1 for r in posts if r["es_del_perfil"] == "si"), pal, pc, pal + pc))
    print("Archivos en: %s" % os.path.abspath(SALIDA))


if __name__ == "__main__":
    main()
