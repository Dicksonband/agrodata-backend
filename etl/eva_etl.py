"""
ETL de EVA (UPRA / MinAgricultura) → Supabase.  Cubre RI-01 y RI-07.

Fuentes en datos.gov.co:
  2pnw-mmge  EVA 2007–2018
  uejq-wxrr  EVA 2019–2023 (Base Agrícola)
Uso:
  python -m etl.eva_etl                         # descarga ambas y carga
  python -m etl.eva_etl --csv ruta1.csv ruta2.csv   # si descargó los CSV a mano
  python -m etl.eva_etl --desde 2015            # solo desde ese año
"""
import argparse
import io
import os
import re
import sys

import pandas as pd
import requests
from dotenv import load_dotenv

from app.core import norm

load_dotenv()
FUENTES = {
    "EVA 2007-2018 (datos.gov.co 2pnw-mmge)": "2pnw-mmge",
    "EVA 2019-2023 (datos.gov.co uejq-wxrr)": "uejq-wxrr",
}
URL_CSV = "https://www.datos.gov.co/api/views/{id}/rows.csv?accessType=DOWNLOAD"


def _h(c):
    """Encabezado normalizado: 'Área Sembrada\n(ha)' -> 'area_sembrada_ha'."""
    return re.sub(r"[^a-z0-9]+", "_", norm(c).lower()).strip("_")


# campo -> función que decide si un encabezado normalizado le corresponde
REGLAS = {
    "cod_dep": lambda h: h.startswith("cod") and "dep" in h and "departamento" not in h,
    "departamento": lambda h: h.startswith("departamento"),
    "cod_mun": lambda h: h.startswith("cod") and "mun" in h and "municipio" not in h,
    "municipio": lambda h: h.startswith("municipio"),
    "cultivo": lambda h: h == "cultivo",
    "anio": lambda h: h in ("ano", "anio", "year") or h.startswith("ano_"),
    "periodo": lambda h: h.startswith("periodo"),
    "ciclo": lambda h: h.startswith("ciclo"),
    "area_sembrada": lambda h: h.startswith("area_sembrada"),
    "area_cosechada": lambda h: h.startswith("area_cosechada"),
    "produccion": lambda h: h.startswith("produccion") and "estado" not in h,
}
OBLIGATORIOS = ["departamento", "municipio", "cultivo", "anio", "area_sembrada"]


def mapear_columnas(df):
    mapa = {}
    for campo, regla in REGLAS.items():
        for c in df.columns:
            if regla(_h(c)) and c not in mapa.values():
                mapa[campo] = c
                break
    faltan = [c for c in OBLIGATORIOS if c not in mapa]
    if faltan:
        raise SystemExit(f"No se encontraron las columnas {faltan}.\n"
                         f"Encabezados del archivo: {[_h(c) for c in df.columns]}\n"
                         "Ajuste REGLAS en etl/eva_etl.py.")
    return mapa


def _num(s):
    """Convierte '1.234,5' / '1234.5' / '' a número."""
    s = s.astype(str).str.strip().str.replace(r"\s", "", regex=True)
    con_coma = s.str.contains(",", na=False)
    s = s.where(~con_coma, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def transformar(df, fuente):
    """Filas municipales → una fila por (año, municipio, cultivo), en hectáreas."""
    m = mapear_columnas(df)
    t = pd.DataFrame({k: df[v] for k, v in m.items()})
    for c in ("area_sembrada", "area_cosechada", "produccion"):
        t[c] = _num(t[c]) if c in t else pd.NA
    t["anio"] = pd.to_numeric(t["anio"], errors="coerce")
    t = t.dropna(subset=["anio", "area_sembrada", "cultivo", "departamento"])
    t["anio"] = t["anio"].astype(int)
    for c in ("cod_dep", "cod_mun", "periodo", "ciclo", "municipio"):
        t[c] = t[c].astype(str).str.strip() if c in t else ""
    t["permanente"] = t["ciclo"].str.upper().str.contains("PERMAN", na=False)

    clave = ["anio", "cod_dep", "departamento", "cod_mun", "municipio", "cultivo", "ciclo", "permanente"]
    # 1) sumar desagregaciones dentro de cada periodo (semestre A/B)
    por_periodo = t.groupby(clave + ["periodo"], dropna=False, as_index=False)[
        ["area_sembrada", "area_cosechada", "produccion"]].sum(min_count=1)
    # 2) anualizar: transitorios suman periodos; permanentes toman el máximo (misma área en A y B)
    vals = ["area_sembrada", "area_cosechada", "produccion"]
    g = por_periodo.groupby(clave, dropna=False)[vals]
    suma = g.sum(min_count=1).reset_index()
    maxi = g.max().reset_index()
    out = suma.copy()
    perm = out["permanente"].values
    for c in vals:
        out[c] = suma[c].where(~perm, maxi[c])
    out = out.drop(columns="permanente")
    out["cultivo_n"] = out["cultivo"].map(norm)
    out["departamento_n"] = out["departamento"].map(norm)
    out["municipio_n"] = out["municipio"].map(norm)
    out["fuente"] = fuente
    return out


def descargar(dataset_id):
    h = {"X-App-Token": os.environ["SOCRATA_APP_TOKEN"]} if os.getenv("SOCRATA_APP_TOKEN") else {}
    r = requests.get(URL_CSV.format(id=dataset_id), headers=h, timeout=300)
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content), dtype=str)


COLS = ["anio", "cod_dep", "departamento", "departamento_n", "cod_mun", "municipio", "municipio_n",
        "cultivo", "cultivo_n", "ciclo", "area_sembrada", "area_cosechada", "produccion", "fuente"]


def cargar(df, anio_desde):
    import psycopg
    df = df[df["anio"] >= anio_desde]
    # el conjunto más nuevo prevalece en años solapados
    df = df.sort_values("fuente").drop_duplicates(
        ["anio", "cod_mun", "cultivo_n", "ciclo"], keep="last")
    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as con:
        with con.cursor() as cur:
            cur.execute("delete from eva_area_anual where anio >= %s", (anio_desde,))
            with cur.copy(f"copy eva_area_anual ({','.join(COLS)}) from stdin") as cp:
                for row in df[COLS].itertuples(index=False):
                    cp.write_row([None if pd.isna(v) else v for v in row])
            for fuente, g in df.groupby("fuente"):
                cur.execute("insert into etl_log (fuente,url,filas,anio_min,anio_max) values (%s,%s,%s,%s,%s)",
                            (fuente, "https://www.datos.gov.co", len(g), int(g.anio.min()), int(g.anio.max())))
        con.commit()
    print(f"Cargadas {len(df)} filas ({df.anio.min()}–{df.anio.max()}).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="*", help="CSV locales en lugar de descargar")
    ap.add_argument("--desde", type=int, default=2012)
    a = ap.parse_args()
    partes = []
    if a.csv:
        for p in a.csv:
            partes.append(transformar(pd.read_csv(p, dtype=str), f"EVA (archivo {os.path.basename(p)})"))
    else:
        for nombre, did in FUENTES.items():
            print("Descargando", nombre, "…")
            partes.append(transformar(descargar(did), nombre))
    cargar(pd.concat(partes, ignore_index=True), a.desde)


if __name__ == "__main__":
    sys.exit(main())
