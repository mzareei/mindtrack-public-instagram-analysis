# -*- coding: utf-8 -*-
"""
Quita de los comentarios el texto que NO escribio nadie: la interfaz de Instagram.

El problema. El raspador toma el texto visible del bloque de comentarios, y ahi
Instagram intercala sus propios controles. Quedaron 140 filas en
`comentarios.csv` que no son comentarios: son fragmentos de la cabecera del
post y de la barra de audio de los reels. Las dos formas tipicas:

    'Following More options usuario_ejemplo1'
    'Audio is muted usuario_ejemplo4 Shakira - Lo Hecho Esta Hecho Following More options usuario_ejemplo14'

Por que importa, y no es cosmetica:

  1. **Son palabras inventadas atribuidas a un paciente.** 95 de las 140 estan
     marcadas `es_del_paciente=si`, con 1,009 palabras en total. Un modelo de
     texto entrenado encima aprende a reconocer "Following More options" como
     lenguaje de paciente, que es exactamente el tipo de artefacto de
     recoleccion que el detector de marco existe para cazar.
  2. **Filtran handles de terceros.** Cada una lleva el usuario de otra persona
     en claro: 103 handles distintos, y de paso titulos de cancion y artistas. Es fuga de anonimato en un corpus que se
     entrego anonimizado.
  3. **Inflan el conteo de palabras** por paciente, que es una de las variables
     del emparejamiento.

Criterio, deliberadamente conservador. Solo se borra lo que no puede ser texto
humano en este corpus:

  a) contiene "More options" / "Mas opciones"  -> 116 filas
     (revisadas una a una: todas son barra de audio de reel o barra de
     etiquetas de foto, ninguna es texto humano)
  b) el texto COMPLETO es "Reply", "Responder", "Verified" o "Verificado"
                                                ->  24 filas

Y solo se recorta la cola "<N> likes" / "<N> me gusta" que Instagram pega al
final de un comentario real (46 filas); el texto de la persona se conserva
entero.

Lo que NO se toca, a proposito: un patron generico del tipo "la fila entera
parece handles y palabras sueltas" tambien habria casado con
'Follow back please @usuario_ejemplo13', que es un comentario real de una persona.
Por eso la regla pide marcadores inequivocos y no una heuristica de forma.

Los captions (`posts.csv`) se auditaron con los mismos patrones y salen limpios:
las 4 coincidencias son texto real ("the following photos", "no tengo tiempo de
responder"). No se tocan.

Nada se borra en silencio: lo eliminado se guarda en
`comentarios_descartados_interfaz.csv` para poder revisarlo.

Uso:
    python ig/analisis/limpiar_interfaz.py [--escribir]

    Sin --escribir solo informa (simulacro). Con --escribir produce
    `resultados_ig/extraccion/comentarios_limpio.csv`.
"""

import csv, os, re, sys
from collections import Counter

# (a) marcador inequivoco de interfaz en cualquier posicion de la fila
CHROME_INEQUIVOCO = re.compile(r'More options|M[áa]s opciones', re.I)

# (b) la fila entera es un solo control de la interfaz
SOLO_CONTROL = re.compile(r'^\s*(Reply|Responder|Verified|Verificad[oa])\s*$', re.I)

# cola que Instagram pega al final de un comentario real
COLA_LIKES = re.compile(r'\s*\b\d[\d.,]*\s*(?:likes?|me gusta)\s*$', re.I)


def _ruta(*p):
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, *p)


def es_interfaz(texto):
    """True si la fila entera es interfaz y hay que descartarla."""
    t = (texto or "").strip()
    if not t:
        return False
    return bool(CHROME_INEQUIVOCO.search(t) or SOLO_CONTROL.match(t))


def limpiar(texto):
    """Recorta la interfaz pegada a un comentario real. Devuelve (texto, tocado)."""
    t = (texto or "").strip()
    nuevo = COLA_LIKES.sub("", t).strip()
    return nuevo, (nuevo != t)


def contar_palabras(t):
    return len([p for p in re.split(r"\s+", (t or "").strip()) if p])


def handles_en(texto):
    fuera = {"following", "follow", "more", "options", "audio", "muted",
             "original", "verified", "reply", "responder", "siguiendo",
             "seguir", "verificado", "verificada", "opciones", "mas"}
    return {h for h in re.findall(r"\b[a-z0-9._]{4,30}\b", (texto or "").lower())
            if h not in fuera and not h.isdigit()}


def main():
    escribir = "--escribir" in sys.argv
    ruta = _ruta("resultados_ig", "extraccion", "comentarios.csv")
    filas = list(csv.DictReader(open(ruta, encoding="utf-8-sig")))
    campos = list(filas[0].keys())

    limpias, descartadas = [], []
    recortadas = 0
    pal_falsas = 0
    handles = set()
    por_paciente = Counter()

    for r in filas:
        t = r.get("texto") or ""
        if es_interfaz(t):
            descartadas.append(r)
            pal_falsas += int(r.get("palabras") or 0)
            por_paciente[r.get("es_del_paciente", "?")] += 1
            handles |= handles_en(t)
            continue
        nuevo, tocado = limpiar(t)
        if tocado:
            recortadas += 1
            r = dict(r)
            r["texto"] = nuevo
            r["palabras"] = contar_palabras(nuevo)
        limpias.append(r)

    print("\nLIMPIEZA DE INTERFAZ EN COMENTARIOS")
    print("=" * 62)
    print("  filas de entrada                     : %5d" % len(filas))
    print("  descartadas por ser solo interfaz    : %5d" % len(descartadas))
    print("     de ellas marcadas como paciente   : %5d" % por_paciente.get("si", 0))
    print("     palabras falsas que se retiran    : %5d" % pal_falsas)
    print("     handles de terceros que llevaban  : %5d" % len(handles))
    print("  comentarios reales con cola recortada: %5d" % recortadas)
    print("  filas de salida                      : %5d" % len(limpias))

    if not escribir:
        print("\n  SIMULACRO. Nada escrito. Repite con --escribir para generar:")
        print("     resultados_ig/extraccion/comentarios_limpio.csv")
        print("     resultados_ig/extraccion/comentarios_descartados_interfaz.csv\n")
        return

    sal = _ruta("resultados_ig", "extraccion", "comentarios_limpio.csv")
    des = _ruta("resultados_ig", "extraccion", "comentarios_descartados_interfaz.csv")
    for destino, datos in ((sal, limpias), (des, descartadas)):
        with open(destino, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(datos)
        print("  -> %s" % destino)
    print()


if __name__ == "__main__":
    main()
