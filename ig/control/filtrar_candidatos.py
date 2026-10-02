# -*- coding: utf-8 -*-
"""
Limpieza de la lista de candidatos, ANTES de gastar horas de scraping.

La cosecha se queda con todos los handles enlazados en la pagina de una semilla.
Eso incluye personas, pero tambien cuentas institucionales, marcas, negocios y
(en el caso de los hashtags genericos) escuelas de otros paises. Cada uno de
esos handles cuesta ~4 minutos de extraccion y no puede ser un control, asi que
conviene tirarlos aqui y no despues.

Tres filtros, en orden de confianza:

  1. INSTITUCIONALES Y MARCAS. Por patron en el nombre de usuario: escuelas,
     universidades, dependencias, negocios, medios. Es heuristico y tiene falsos
     positivos (una persona real que se llame "gymjulia" cae), asi que TODO lo
     descartado se escribe en candidatos_descartados.csv para revisarlo a ojo y
     rescatar lo que haga falta.
  2. AÑO DE NACIMIENTO EN EL HANDLE. "usuario_ejemplo5" implica 47 años. Es de
     alta precision cuando el año es anterior a 1997 o posterior a 2012.
  3. SEMILLAS COMPLETAS. Con --sin-semilla se tira todo lo que vino de una
     semilla que resulto mala. Los hashtags genericos de generacion son el caso
     tipico: #generacion2026 se usa en toda Latinoamerica y trae escuelas de
     Chile y Argentina, que no sirven como control de una muestra de Jalisco.

Uso:
    python ig/control/filtrar_candidatos.py
    python ig/control/filtrar_candidatos.py --sin-semilla generacion2026,generacion2025
    python ig/control/filtrar_candidatos.py --rescatar handle1,handle2
"""

import csv, os, re, sys
from collections import Counter
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(DIR, "candidatos.csv")
SALIDA = os.path.join(DIR, "candidatos.csv")
DESCARTES = os.path.join(DIR, "candidatos_descartados.csv")
FORMATO = os.path.join(DIR, "candidatos_formato.csv")

ANIO_ACTUAL = datetime.now().year
EDAD_MIN, EDAD_MAX = 15, 29

# Patrones de cuenta que no es de una persona. Conservador a proposito: mejor
# dejar pasar una marca (el scraper la marcara y emparejar.py la tirara por la
# envolvente) que tirar a una persona real.
INSTITUCIONAL = re.compile(
    r"(oficial|_mx$|^sep$|^sepmx|udg|udeg|prepa[._]?\d|escuela|universidad|colegio"
    r"|cucei|cucs\b|cucea|cucsh|cuaad|cutonala|cusur|cucosta|cualtos|cucienega|cuvalles"
    r"|cicej|ieee|coordinaci|brigada|ballet|comunidad|colectivo|vinculacion|salud_digital"
    r"|^(?:dr|dra|lic|ing|mtro|mtra|psic|arq|cp|dent)[._]"
    r"|instituto|centro_|admision|campus|facultad|academia|posgrado|maestria"
    r"|clinica|terapia|consultorio|hospital|^dr[._]|^dra[._]|nutcucs|udeportes"
    r"|studio|store|shop|boutique|tienda|ventas|negocio|emprend"
    r"|fest$|eventos|agency|agencia|marketing|publicidad"
    r"|fotografia|photography|fotos|barberia|salon|gym|fitness|nutricion"
    r"|cafe$|resto|pizza|tacos|antojitos|carnes|birria|mariscos|tortilleria|panaderia|reposteria"
    r"|music|band|radio|revista|news|noticias|prensa|podcast"
    r"|deportes|futbol|team|club|liga)", re.I)

ANIO = re.compile(r"(19[5-9]\d|20[0-2]\d)")


def edad_implicita(usuario):
    """Si el handle lleva un año de nacimiento, devuelve la edad que implica."""
    m = ANIO.search(usuario)
    if not m:
        return None
    anio = int(m.group(1))
    if not (1950 <= anio <= ANIO_ACTUAL - 10):
        return None
    return ANIO_ACTUAL - anio


def main():
    def arg(n, d=""):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d

    fuera_semillas = {s.strip() for s in arg("--sin-semilla").split(",") if s.strip()}
    rescatar = {s.strip().lower() for s in arg("--rescatar").split(",") if s.strip()}

    if not os.path.exists(ENTRADA):
        sys.exit("No encuentro %s. Corre antes cosechar_candidatos.py." % ENTRADA)
    filas = list(csv.DictReader(open(ENTRADA, encoding="utf-8-sig")))
    print("\nLIMPIEZA DE CANDIDATOS")
    print("  entrada: %d handles\n" % len(filas))

    buenos, malos = [], []
    for f in filas:
        u = f["usuario"]
        if u.lower() in rescatar:
            buenos.append(f)
            continue
        motivo = ""
        if f["semilla"] in fuera_semillas:
            motivo = "semilla descartada: %s" % f["semilla"]
        elif INSTITUCIONAL.search(u):
            motivo = "parece cuenta institucional o de negocio"
        else:
            e = edad_implicita(u)
            if e is not None and not (EDAD_MIN <= e <= EDAD_MAX):
                motivo = "año en el handle implica %d años" % e
        if motivo:
            malos.append({**f, "motivo_descarte": motivo})
        else:
            buenos.append(f)

    print("  Descartados: %d" % len(malos))
    for motivo, n in Counter(m["motivo_descarte"].split(":")[0] for m in malos).most_common():
        print("    %-42s %d" % (motivo, n))
    print("\n  Quedan: %d handles" % len(buenos))
    print("\n  Por semilla:")
    for k, n in Counter(b["semilla"] for b in buenos).most_common():
        print("    %-24s %d" % (k, n))

    if malos:
        with open(DESCARTES, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(malos[0].keys()))
            w.writeheader()
            w.writerows(malos)
        print("\n  -> %s  (revisalo: el filtro de marcas tiene falsos positivos;" % DESCARTES)
        print("     para recuperar a alguien usa --rescatar handle1,handle2)")

    columnas = ["usuario", "tipo_semilla", "semilla", "clase_semilla", "banda_esperada",
                "tipo_evidencia", "shortcode_evidencia", "fecha_cosecha"]
    with open(SALIDA, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas)
        w.writeheader()
        w.writerows([{k: b.get(k, "") for k in columnas} for b in buenos])

    # 2) Las cuentas institucionales descartadas que parecen ESCUELAS u
    #    organizaciones estudiantiles no se tiran: se convierten en semillas
    #    nuevas. Es la forma de que la cosecha crezca sola sin buscar handles
    #    a mano. (Bola de nieve sobre instituciones, no sobre personas.)
    ESCUELA = re.compile(r"(prepa|preparatoria|bachillerato|cbtis|conalep|cecytej|cetis|vocacional|politecnico)", re.I)
    UNIVERSIDAD = re.compile(r"(cucei|cucs|cucea|cucsh|cuaad|cutonala|cusur|cucosta|cualtos|cucienega|cuvalles|cunorte|culagos|cutlajo|cu_|universidad|facultad|licenciatura)", re.I)
    ORG = re.compile(r"(xpresion|feu\b|consejo|sociedad|colectivo|brigada|robotica|ballet|club|equipo|generacion)", re.I)
    ruta_sem = os.path.join(DIR, "semillas_descubiertas.txt")
    previas = set()
    if os.path.exists(ruta_sem):
        previas = {l.split(",")[0].strip().lower() for l in open(ruta_sem, encoding="utf-8")
                   if l.strip() and not l.startswith("#")}
    conocidas = set()
    try:
        sys.path.insert(0, DIR)
        import cosechar_candidatos as cc
        conocidas = {s_["valor"].lower() for s_ in cc.SEMILLAS}
    except Exception:
        pass
    nuevas = []
    for m in malos:
        u = m["usuario"].lower()
        if u in previas or u in conocidas or not m["motivo_descarte"].startswith("parece cuenta"):
            continue
        # Solo Jalisco: fuera lo que se declare de otro estado o pais.
        if re.search(r"(qro|queretaro|cdmx|monterrey|puebla|usach|chile|argentina|colombia|peru|\bmx$)", u):
            continue
        if ESCUELA.search(u):
            nuevas.append((u, "prepa"))
        elif UNIVERSIDAD.search(u):
            nuevas.append((u, "universidad"))
        elif ORG.search(u):
            nuevas.append((u, "org_estudiantil"))
    if nuevas:
        with open(ruta_sem, "a", encoding="utf-8") as fh:
            if not previas:
                fh.write("# Semillas descubiertas automaticamente por filtrar_candidatos.py.\n"
                         "# handle,clase,nota. Revisar de vez en cuando; una que devuelva 0 dos\n"
                         "# veces se apaga sola.\n")
            for u, clase in nuevas:
                fh.write("%s,%s,descubierta %s\n" % (u, clase, datetime.now().date().isoformat()))
        print("\n  Semillas nuevas descubiertas: %d -> %s" % (len(nuevas), ruta_sem))
        for u, clase in nuevas[:15]:
            print("     %-32s %s" % (u, clase))

    with open(FORMATO, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "F. Inicio", "F. Fin", "instagram", "facebook", "tiktok", "X/Twitter"])
        hoy = datetime.now().strftime("%m/%d/%Y")
        for n, b in enumerate(buenos, 1):
            w.writerow(["CTRL%04d" % n, "1/1/2010", hoy, b["usuario"], "", "", ""])

    horas = len(buenos) * 4 / 60.0
    print("  -> %s" % SALIDA)
    print("  -> %s\n" % FORMATO)
    print("  Extraer estos %d perfiles cuesta ~%.0f horas a 4 min por perfil." % (len(buenos), horas))
    print("  ANTES de lanzar la corrida completa, haz un piloto de 50 y mide el")
    print("  rendimiento real:")
    print("     python ig/control/piloto.py --n 50\n")


if __name__ == "__main__":
    main()
