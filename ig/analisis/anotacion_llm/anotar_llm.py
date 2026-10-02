# -*- coding: utf-8 -*-
"""
Capa 2 con dos modelos: cada publicacion del kit ciego la codifican DOS modelos
de lenguaje distintos, por separado, con el mismo libro de codigos.

Por que dos. Por lo mismo que se usan dos anotadores humanos: el acuerdo entre
ellos es la unica evidencia de que las etiquetas miden algo. Donde los dos
coinciden, la etiqueta se acepta; donde no, decide una persona
(`acuerdo.py` genera esa cola). El trabajo humano baja de 212 posts doblemente
codificados a unas decenas de adjudicaciones mas una muestra de validez.

Ciego. Cada llamada lleva UN post: codigo opaco, texto e imagen. Ni fecha, ni
paciente, ni ventana, ni los otros posts. El modelo no puede construir una
historia por persona porque no sabe quien es nadie.

Gobernanza. Esto envia captions e imagenes (anonimizados: sin handles, sin
ids, nombre de fichero opaco) a las APIs de Anthropic y OpenAI. Ninguna de
las dos entrena con lo que recibe por API, pero es tratamiento por un tercero
fuera de Mexico. Confirmar con la investigadora responsable y el CEIC que la
aprobacion vigente lo cubre ANTES de correr sobre el corpus completo. El modo
--prueba 3 sirve para verificar credenciales con tres posts.

Uso:
    python ig/analisis/anotacion_llm/anotar_llm.py --prueba 3     # 3 posts, cada modelo, imprime la respuesta
    python ig/analisis/anotacion_llm/anotar_llm.py                # los 212, los dos modelos, reanudable
    python ig/analisis/anotacion_llm/anotar_llm.py --solo anthropic
    python ig/analisis/anotacion_llm/anotar_llm.py --simular      # etiquetas falsas con semilla, para probar el resto

Credenciales, en C:\\Github\\Mindtrack\\.env (o variables de entorno):
    ANTHROPIC_API_KEY=...
    OPENAI_API_KEY=...
    ANTHROPIC_MODEL=claude-sonnet-4-5      (opcional; este es el valor por defecto)
    OPENAI_MODEL=gpt-4o                    (opcional; idem)

Salida: resultados_ig/capa2/etiquetas_<proveedor>.jsonl (una linea por post,
reanudable) y etiquetas_<proveedor>.csv.

Sin SDKs: urllib de la biblioteca estandar. Temperatura 0. Reintentos con
espera creciente. Imagenes en base64 tal cual (JPEG de Instagram, ~100-300 KB).
"""

import base64, csv, json, os, random, sys, time
import urllib.request, urllib.error

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
ANOT = os.path.join(RAIZ, "anotacion")
SAL = os.path.join(RAIZ, "resultados_ig", "capa2")

CODIGOS = ["expresion_simbolica", "desesperanza", "carga_percibida", "pertenencia",
           "dolor_psiquico", "atrapamiento", "busqueda_de_apoyo", "despedida"]
CAMPOS = CODIGOS + ["orientacion_temporal", "confianza", "justificacion"]

PROVEEDORES = {
    "anthropic": {"url": "https://api.anthropic.com/v1/messages", "clave": "ANTHROPIC_API_KEY",
                  "modelo_env": "ANTHROPIC_MODEL", "modelo_defecto": "claude-sonnet-4-5"},
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "clave": "OPENAI_API_KEY",
               "modelo_env": "OPENAI_MODEL", "modelo_defecto": "gpt-4o"},
}


def cargar_env():
    ruta = os.path.join(RAIZ, ".env")
    if os.path.exists(ruta):
        for l in open(ruta, encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


def prompt_sistema():
    return open(os.path.join(DIR, "prompt_codebook.md"), encoding="utf-8").read()


def leer_corpus():
    ruta = os.path.join(ANOT, "corpus_anotacion.csv")
    if not os.path.exists(ruta):
        sys.exit("Falta anotacion/corpus_anotacion.csv. Corre antes ig/analisis/exportar_anotacion.py")
    filas = list(csv.DictReader(open(ruta, encoding="utf-8-sig")))
    for f in filas:
        f["_img"] = os.path.join(ANOT, f["imagen"]) if f.get("imagen") else ""
    return filas


def mensaje_usuario(fila):
    texto = (fila.get("texto") or "").strip()
    partes = ["Publicacion %s." % fila["codigo"]]
    partes.append("Texto: %s" % (('"%s"' % texto) if texto else "(sin texto)"))
    partes.append("Imagen: %s" % ("adjunta" if (fila["_img"] and os.path.exists(fila["_img"])) else "no disponible"))
    partes.append("Responde solo con el JSON.")
    return "\n".join(partes)


def imagen_b64(ruta):
    if not ruta or not os.path.exists(ruta):
        return None
    with open(ruta, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def llamar(proveedor, sistema, usuario, img_b64, modelo, timeout=90):
    P = PROVEEDORES[proveedor]
    clave = os.environ.get(P["clave"])
    if not clave:
        raise RuntimeError("Falta %s en .env o en el entorno" % P["clave"])
    if proveedor == "anthropic":
        contenido = []
        if img_b64:
            contenido.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}})
        contenido.append({"type": "text", "text": usuario})
        cuerpo = {"model": modelo, "max_tokens": 400, "temperature": 0, "system": sistema,
                  "messages": [{"role": "user", "content": contenido}]}
        cab = {"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    else:
        contenido = [{"type": "text", "text": usuario}]
        if img_b64:
            contenido.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img_b64, "detail": "low"}})
        cuerpo = {"model": modelo, "temperature": 0, "max_tokens": 400,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": contenido}]}
        cab = {"Authorization": "Bearer " + clave, "content-type": "application/json"}
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(P["url"], data=datos, headers=cab, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    if proveedor == "anthropic":
        return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    return resp["choices"][0]["message"]["content"]


def parsear(texto):
    """Saca el JSON aunque venga envuelto en ```json ... ``` o con texto alrededor."""
    t = (texto or "").strip()
    if "```" in t:
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t
        t = t[4:] if t.lower().startswith("json") else t
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("sin JSON: %r" % texto[:120])
    d = json.loads(t[i:j + 1])
    out = {}
    for c in CODIGOS:
        v = d.get(c, 0)
        out[c] = 1 if str(v).strip() in ("1", "true", "True", "si", "sí") else 0
    ot = str(d.get("orientacion_temporal", "") or "").strip().lower()[:3]
    out["orientacion_temporal"] = ot if ot in ("pas", "pre", "fut") else ""
    cf = str(d.get("confianza", "") or "").strip().lower()
    out["confianza"] = cf if cf in ("alta", "media", "baja") else "media"
    out["justificacion"] = str(d.get("justificacion", "") or "").strip()[:300]
    return out


def con_reintentos(fn, intentos=5):
    espera = 3
    for i in range(intentos):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode("utf-8", "replace")[:300]
            if e.code in (400, 401, 403):
                raise RuntimeError("HTTP %d (no reintento): %s" % (e.code, cuerpo))
            print("    HTTP %d, reintento en %ds: %s" % (e.code, espera, cuerpo[:120]), flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            print("    %s: %s, reintento en %ds" % (type(e).__name__, str(e)[:120], espera), flush=True)
        time.sleep(espera)
        espera = min(espera * 2, 60)
    raise RuntimeError("agotados los reintentos")


def etiquetar(proveedor, filas, modelo, log=print):
    os.makedirs(SAL, exist_ok=True)
    ruta_jsonl = os.path.join(SAL, "etiquetas_%s.jsonl" % proveedor)
    hechos = {}
    if os.path.exists(ruta_jsonl):
        for l in open(ruta_jsonl, encoding="utf-8"):
            try:
                d = json.loads(l)
                hechos[d["codigo"]] = d
            except Exception:
                pass
    pendientes = [f for f in filas if f["codigo"] not in hechos]
    log("  %s (%s): %d hechos, %d pendientes" % (proveedor, modelo, len(hechos), len(pendientes)))
    sistema = prompt_sistema()
    t0 = time.time()
    with open(ruta_jsonl, "a", encoding="utf-8") as out:
        for k, f in enumerate(pendientes, 1):
            img = imagen_b64(f["_img"])
            usuario = mensaje_usuario(f)
            def una():
                return parsear(llamar(proveedor, sistema, usuario, img, modelo))
            try:
                et = con_reintentos(una)
            except RuntimeError as e:
                log("    %s: ERROR definitivo: %s" % (f["codigo"], e))
                if "401" in str(e) or "403" in str(e) or "Falta" in str(e):
                    raise
                continue
            reg = {"codigo": f["codigo"], "proveedor": proveedor, "modelo": modelo,
                   "tiene_imagen": bool(img), "tiene_texto": f.get("tiene_texto") == "si"}
            reg.update(et)
            out.write(json.dumps(reg, ensure_ascii=False) + "\n")
            out.flush()
            hechos[f["codigo"]] = reg
            if k % 10 == 0 or k == len(pendientes):
                por = (time.time() - t0) / k
                log("    %d/%d  (%.1f s/post, faltan ~%.0f min)" % (k, len(pendientes), por, por * (len(pendientes) - k) / 60))
            time.sleep(0.5)
    escribir_csv(proveedor, hechos, filas)
    return hechos


def escribir_csv(proveedor, hechos, filas):
    ruta = os.path.join(SAL, "etiquetas_%s.csv" % proveedor)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "proveedor", "modelo", "tiene_texto", "tiene_imagen"] + CAMPOS)
        for fila in filas:
            d = hechos.get(fila["codigo"])
            if not d:
                continue
            w.writerow([d["codigo"], d["proveedor"], d["modelo"], int(bool(d.get("tiene_texto"))), int(bool(d.get("tiene_imagen")))] +
                       [d.get(c, "") for c in CAMPOS])
    return ruta


def simular(filas, log=print):
    """Etiquetas falsas para probar acuerdo.py y contraste_capa2.py sin gastar
    ni una llamada. Dos 'modelos' que coinciden ~80% de las veces."""
    os.makedirs(SAL, exist_ok=True)
    rng = random.Random(20260910)
    base = {}
    for f in filas:
        base[f["codigo"]] = {c: (1 if rng.random() < 0.12 else 0) for c in CODIGOS}
    for prov in ("anthropic", "openai"):
        hechos = {}
        for f in filas:
            et = dict(base[f["codigo"]])
            for c in CODIGOS:
                if rng.random() < 0.08:
                    et[c] = 1 - et[c]
            et["orientacion_temporal"] = rng.choice(["pas", "pre", "fut", ""])
            et["confianza"] = rng.choice(["alta", "media", "baja"])
            et["justificacion"] = "simulado"
            reg = {"codigo": f["codigo"], "proveedor": prov, "modelo": "SIMULADO",
                   "tiene_imagen": bool(f["_img"]), "tiene_texto": f.get("tiene_texto") == "si"}
            reg.update(et)
            hechos[f["codigo"]] = reg
        with open(os.path.join(SAL, "etiquetas_%s.jsonl" % prov), "w", encoding="utf-8") as out:
            for d in hechos.values():
                out.write(json.dumps(d, ensure_ascii=False) + "\n")
        escribir_csv(prov, hechos, filas)
        log("  %s: %d etiquetas SIMULADAS" % (prov, len(hechos)))


def main():
    cargar_env()
    filas = leer_corpus()
    if "--simular" in sys.argv:
        print("MODO SIMULACION: etiquetas falsas, ninguna llamada a ninguna API.")
        simular(filas)
        return
    n_prueba = int(sys.argv[sys.argv.index("--prueba") + 1]) if "--prueba" in sys.argv else 0
    solo = sys.argv[sys.argv.index("--solo") + 1] if "--solo" in sys.argv else None
    provs = [solo] if solo else list(PROVEEDORES)
    for p in provs:
        if p not in PROVEEDORES:
            sys.exit("Proveedor desconocido: %s" % p)
        if not os.environ.get(PROVEEDORES[p]["clave"]):
            sys.exit("Falta %s. Ponla en C:\\Github\\Mindtrack\\.env" % PROVEEDORES[p]["clave"])
    print("ANOTACION CON MODELOS DE LENGUAJE")
    print("  corpus: %d publicaciones (ciego: codigo + texto + imagen, nada mas)" % len(filas))
    if n_prueba:
        muestra = filas[:n_prueba]
        sistema = prompt_sistema()
        for p in provs:
            modelo = os.environ.get(PROVEEDORES[p]["modelo_env"], PROVEEDORES[p]["modelo_defecto"])
            print("\n  PRUEBA %s (%s), %d posts:" % (p, modelo, n_prueba))
            for f in muestra:
                img = imagen_b64(f["_img"])
                try:
                    crudo = llamar(p, sistema, mensaje_usuario(f), img, modelo)
                    et = parsear(crudo)
                    print("    %s  texto=%r" % (f["codigo"], (f.get("texto") or "")[:50]))
                    print("      -> " + json.dumps(et, ensure_ascii=False))
                except Exception as e:
                    print("    %s  ERROR: %s" % (f["codigo"], e))
        print("\n  Si las respuestas tienen sentido, corre sin --prueba para el corpus completo.")
        return
    for p in provs:
        modelo = os.environ.get(PROVEEDORES[p]["modelo_env"], PROVEEDORES[p]["modelo_defecto"])
        etiquetar(p, filas, modelo)
    print("\n  Listo. Siguiente: python ig/analisis/anotacion_llm/correr_capa2.py")


if __name__ == "__main__":
    main()
