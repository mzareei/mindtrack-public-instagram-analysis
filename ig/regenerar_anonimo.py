# -*- coding: utf-8 -*-
"""
Regenera el JSON anonimo a partir de un global ya existente, sin volver a
scrapear nada.

Sirve cuando la anonimizacion se corrige despues de una corrida. Paso justo eso
el 28/08/2026: la descarga de media anadio los campos `media_local` y
`video_local` con la forma "media/<usuario>/<shortcode>.jpg", no estaban en la
lista de campos a limpiar, y el export salio con 30 usuarios reales dentro.

Uso:
    python ig/regenerar_anonimo.py                           # el global mas reciente
    python ig/regenerar_anonimo.py resultados_ig/global_X.json
"""
import os, sys, glob, json, types

# Este script no abre navegador. Si selenium no esta instalado (por ejemplo en
# un servidor donde solo se procesan los JSON), se sustituye por un stub para
# poder importar el modulo del scraper y reusar su logica de anonimizacion.
try:
    import selenium  # noqa: F401
except ImportError:
    for _n in ["selenium", "selenium.webdriver", "selenium.webdriver.common",
               "selenium.webdriver.common.by", "selenium.webdriver.common.keys",
               "selenium.webdriver.support", "selenium.webdriver.support.ui",
               "selenium.webdriver.support.expected_conditions"]:
        sys.modules[_n] = types.ModuleType(_n)
    sys.modules["selenium.webdriver.common.by"].By = type("By", (), {"CSS_SELECTOR": "css"})
    sys.modules["selenium.webdriver.common.keys"].Keys = type("Keys", (), {})
    sys.modules["selenium.webdriver.support.ui"].WebDriverWait = object
    sys.modules["selenium"].webdriver = sys.modules["selenium.webdriver"]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrappingData_ig as S

RESULTADOS_DIR = S.RESULTADOS_DIR


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
    reales = json.load(open(ruta, encoding="utf-8")).get("resultados", [])
    print("Perfiles: %d\n" % len(reales))

    # Handles de TODA la corrida: sin esto, el anonimo de un perfil deja al
    # descubierto a otro perfil de la misma corrida (fuga del 05/09/2026).
    handles_corrida = {(r.get("usuario") or r.get("username") or "").strip() for r in reales}
    handles_corrida |= {(p.get("autor_post") or "")
                        for r in reales for p in (r.get("posts_data") or [])}
    handles_corrida = {h for h in handles_corrida if h}
    print("Handles de la corrida: %d" % len(handles_corrida))
    anonimos = [S.construir_resultado_anonimo(r, handles_corrida) for r in reales]
    fugas = S.verificar_anonimato(anonimos, reales)

    if fugas:
        print("\nNo escribo nada: el resultado sigue teniendo fugas.")
        print("Revisa construir_resultado_anonimo() antes de volver a intentarlo.")
        return 1

    salida = S.save_json({"resultados": anonimos}, "global_anonimo")
    print("\nListo: %s" % salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
