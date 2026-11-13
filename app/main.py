"""AgroData APP · API (FastAPI + Supabase Postgres)."""
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import jwt
import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from .core import calcular_presion, norm

load_dotenv()
UM_Y = float(os.getenv("UMBRAL_AMARILLO", 1.10))
UM_R = float(os.getenv("UMBRAL_ROJO", 1.30))
pool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    # prepare_threshold=None: compatible con el pooler de Supabase
    pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5,
                          kwargs={"row_factory": dict_row, "prepare_threshold": None}, open=True)
    yield
    pool.close()


app = FastAPI(title="AgroData APP API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


def q(sql, params=None):
    with pool.connection() as c:
        cur = c.execute(sql, params or ())
        return cur.fetchall() if cur.description else []


_jwks = None


def _verificar_local(token):
    """Verificación local del JWT (JWKS en proyectos nuevos, HS256 en antiguos)."""
    global _jwks
    if jwt.get_unverified_header(token).get("alg") == "HS256":
        key, algs = os.environ["SUPABASE_JWT_SECRET"], ["HS256"]
    else:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/.well-known/jwks.json")
        key, algs = _jwks.get_signing_key_from_jwt(token).key, ["ES256", "RS256"]
    return jwt.decode(token, key, algorithms=algs, audience="authenticated", leeway=60)["sub"]


def _verificar_remoto(token):
    """Respaldo: pregunta a Supabase Auth si el token es válido y de quién es."""
    r = requests.get(os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/user", timeout=10,
                     headers={"apikey": os.environ["SUPABASE_KEY"], "Authorization": "Bearer " + token})
    if r.status_code != 200:
        raise ValueError(f"Supabase respondió {r.status_code}: {r.text[:200]}")
    return r.json()["id"]


def usuario(authorization: str = Header(default="")) -> str:
    """RNF-03: identifica al usuario a partir del token de sesión de Supabase."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Falta el token de sesión.")
    token = authorization[7:]
    try:
        return _verificar_local(token)
    except Exception as e:
        print("AVISO verificación local falló:", repr(e))
    try:
        return _verificar_remoto(token)
    except Exception as e:
        print("ERROR verificación remota falló:", repr(e))
        raise HTTPException(401, "Sesión inválida o vencida.")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/catalogo")
def catalogo():
    """Cultivos y departamentos con datos EVA (para los selectores)."""
    cult = q("select cultivo_n, min(cultivo) as cultivo, sum(area) as total from eva_depto "
             "group by cultivo_n order by total desc nulls last limit 60")
    dep = q("select distinct departamento_n, departamento from eva_depto order by departamento")
    return {"cultivos": cult, "departamentos": dep}


def _aporte(cultivo_n, dep_n):
    r = q("select coalesce(sum(area_ha),0) as a, count(*) as n from siembras "
          "where cultivo_n=%s and departamento_n=%s", (cultivo_n, dep_n))[0]
    return float(r["a"]), r["n"]


@app.get("/api/presion")
def presion(cultivo: str, departamento: str, amarillo: float = UM_Y, rojo: float = UM_R):
    """RF-05, RF-06, RF-08: consulta por región + semáforo de sobreoferta."""
    c, d = norm(cultivo), norm(departamento)
    serie = q("select anio, area, fuente from eva_depto where cultivo_n=%s and departamento_n=%s "
              "order by anio", (c, d))
    aporte, n = _aporte(c, d)
    res = calcular_presion([(s["anio"], s["area"]) for s in serie], aporte, amarillo, rojo)
    return {"cultivo": cultivo, "departamento": departamento, "n_aportes": n,
            "fuente": serie[-1]["fuente"] if serie else None,
            "serie": [{"anio": s["anio"], "area": float(s["area"] or 0)} for s in serie],
            "umbrales": {"amarillo": amarillo, "rojo": rojo}, **res}


@app.get("/api/alertas")
def alertas(departamento: str, solo_alertas: bool = True, limite: int = Query(30, le=100)):
    """Reporte (RF-12): cultivos del departamento ordenados por presión de oferta."""
    d = norm(departamento)
    rows = q("select anio, cultivo_n, cultivo, area from eva_depto where departamento_n=%s "
             "and anio >= (select max(anio)-6 from eva_depto) order by cultivo_n, anio", (d,))
    aportes = {r["cultivo_n"]: float(r["a"]) for r in q(
        "select cultivo_n, sum(area_ha) as a from siembras where departamento_n=%s "
        "group by cultivo_n", (d,))}
    por = {}
    for r in rows:
        por.setdefault((r["cultivo_n"], r["cultivo"]), []).append((r["anio"], r["area"]))
    out = []
    for (cn, nombre), serie in por.items():
        r = calcular_presion(serie, aportes.get(cn, 0), UM_Y, UM_R)
        if r["indice"] is not None and (not solo_alertas or r["nivel"] != "verde"):
            out.append({"cultivo": nombre, **r})
    out.sort(key=lambda x: x["indice"], reverse=True)
    return {"departamento": departamento, "alertas": out[:limite]}


class SiembraIn(BaseModel):
    cultivo: str = Field(min_length=2, max_length=80)
    departamento: str = Field(min_length=2, max_length=60)
    municipio: str | None = Field(default=None, max_length=80)
    area_ha: float = Field(gt=0, le=100000)
    fecha_siembra: date | None = None
    tipo: Literal["planeada", "establecida"]


@app.post("/api/siembras", status_code=201)
def crear_siembra(s: SiembraIn, uid: str = Depends(usuario)):
    r = q("insert into siembras (user_id,cultivo,cultivo_n,departamento,departamento_n,municipio,"
          "area_ha,fecha_siembra,tipo) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
          (uid, s.cultivo, norm(s.cultivo), s.departamento, norm(s.departamento),
           s.municipio, s.area_ha, s.fecha_siembra, s.tipo))
    return {"id": str(r[0]["id"])}


@app.get("/api/siembras/mias")
def mis_siembras(uid: str = Depends(usuario)):
    return q("select id::text as id, cultivo, departamento, municipio, area_ha, fecha_siembra, tipo "
             "from siembras where user_id=%s order by creado_en desc", (uid,))


@app.delete("/api/siembras/{sid}", status_code=204)
def borrar_siembra(sid: str, uid: str = Depends(usuario)):
    q("delete from siembras where id=%s and user_id=%s", (sid, uid))


@app.get("/api/fuentes")
def fuentes():
    """RI-07: procedencia y fecha de actualización de los datos."""
    return q("select fuente, url, filas, anio_min, anio_max, ejecutado_en from etl_log "
             "order by ejecutado_en desc limit 10")
