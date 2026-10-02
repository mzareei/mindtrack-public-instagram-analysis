# -*- coding: utf-8 -*-
"""
Re-evalua TODO el triaje con las reglas actuales, sin abrir el navegador.

Sirve cada vez que se afinan las reglas (organizaciones, geografia, roles
adultos, lectura de edad): el checkpoint guarda estado, seguidores, posts y bio
de cada perfil ya visitado, asi que se puede volver a juzgar en segundos.
Reescribe triaje.csv, candidatos_aprobados_formato.csv,
candidatos_pendientes_formato.csv y controles_evidencia.csv.

Uso:
    python ig/control/reevaluar.py
"""
import json, os, sys
DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import triaje, verificar_captions as vc

def main():
    env = triaje.cargar_envolvente()
    evid = triaje.cargar_evidencia()
    if not os.path.exists(triaje.CKPT):
        sys.exit("No hay triaje_en_curso.json.")
    hechos = json.load(open(triaje.CKPT, encoding="utf-8"))
    from collections import Counter
    antes = Counter(x.get("veredicto", "?") for x in hechos.values())
    hechos = triaje.migrar_y_reevaluar(hechos, env, evid, False, log=print)
    json.dump(hechos, open(triaje.CKPT, "w", encoding="utf-8"), ensure_ascii=False)
    n_ap, n_pe = triaje.escribir_salidas(hechos)
    despues = Counter(x["veredicto"] for x in hechos.values())
    print("antes  :", dict(antes))
    print("despues:", dict(despues))
    vc.escribir_maestro(print)
    print("-> %d aprobados, %d pendientes de captions" % (n_ap, n_pe))

if __name__ == "__main__":
    main()
