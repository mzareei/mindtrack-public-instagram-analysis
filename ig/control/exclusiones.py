# -*- coding: utf-8 -*-
"""
Lista de handles que NO pueden entrar al grupo control.

Los amigos, familiares y comentaristas de un paciente no son poblacion general.
Comparten ciudad, escuela, circulo y a menudo el mismo evento que llevo al
paciente al hospital. Meterlos como controles contamina el contraste en la
direccion que mas duele: hace que casos y controles se parezcan justo en lo que
importa, y el modelo pierde la señal real.

Al reves tambien: si por azar uno de esos handles es en realidad otro paciente
del estudio, entraria como control siendo caso.

Este modulo junta, del corpus ya extraido:
  - los handles de los propios pacientes (81)
  - los autores de todos los comentarios (1,079 terceros distintos)
  - las cuentas mencionadas en captions y biografias
  - los autores de los posts ajenos que aparecieron en las rejillas

Uso:
    python ig/control/exclusiones.py          -> escribe exclusiones_red.txt
    from exclusiones import cargar_exclusiones
"""

import csv, os, re, sys


def _ruta(*p):
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, *p)


def _norm(u):
    if not u:
        return None
    u = re.sub(r"https?://(www\.)?instagram\.com/|@", "", str(u).strip()).strip("/")
    u = u.split("?")[0].split("/")[0].strip().lower()
    return u or None


def construir(dir_extraccion=None):
    d = dir_extraccion or _ruta("resultados_ig", "extraccion")
    fuera, motivos = set(), {}

    def add(u, motivo):
        u = _norm(u)
        if u:
            fuera.add(u)
            motivos.setdefault(u, motivo)

    ruta = os.path.join(d, "perfiles.csv")
    if os.path.exists(ruta):
        for r in csv.DictReader(open(ruta, encoding="utf-8-sig")):
            add(r.get("usuario"), "paciente")
            for m in re.findall(r"@([\w.]+)", r.get("biografia", "") or ""):
                add(m, "mencion en bio de paciente")

    ruta = os.path.join(d, "posts.csv")
    if os.path.exists(ruta):
        for r in csv.DictReader(open(ruta, encoding="utf-8-sig")):
            add(r.get("autor_post"), "autor de post en rejilla de paciente")
            for m in re.findall(r"@?([\w.]+)", r.get("menciones", "") or ""):
                add(m, "mencionado por paciente")

    ruta = os.path.join(d, "comentarios.csv")
    if os.path.exists(ruta):
        for r in csv.DictReader(open(ruta, encoding="utf-8-sig")):
            add(r.get("autor"), "comento en post de paciente")

    return fuera, motivos


def cargar_exclusiones(ruta=None):
    """Lee la lista ya escrita, o la construye al vuelo si no existe."""
    ruta = ruta or _ruta("ig", "control", "exclusiones_red.txt")
    if os.path.exists(ruta):
        return {l.split("\t")[0].strip().lower()
                for l in open(ruta, encoding="utf-8") if l.strip() and not l.startswith("#")}
    return construir()[0]


if __name__ == "__main__":
    fuera, motivos = construir()
    salida = _ruta("ig", "control", "exclusiones_red.txt")
    with open(salida, "w", encoding="utf-8") as f:
        f.write("# Handles excluidos del grupo control. NO publicar este archivo:\n"
                "# es la red social de los pacientes y por si solo es identificante.\n"
                "# Generado por ig/control/exclusiones.py\n")
        for u in sorted(fuera):
            f.write("%s\t%s\n" % (u, motivos[u]))
    from collections import Counter
    print("%d handles excluidos -> %s" % (len(fuera), salida))
    for motivo, n in Counter(motivos.values()).most_common():
        print("   %-42s %d" % (motivo, n))
    print("\nOJO: este archivo es sensible. Esta fuera del anonimo y no debe salir")
    print("del equipo ni subirse al repositorio. Añadelo a .gitignore.")
