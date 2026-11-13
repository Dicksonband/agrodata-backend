# AgroData APP · Backend (FastAPI + Supabase)

## 1. Base de datos (Supabase, plan gratuito)
1. Cree un proyecto en supabase.com.
2. SQL Editor → pegue y ejecute `schema.sql`.
3. Project Settings → Database: copie la cadena de conexión (pooler) → `DATABASE_URL`.
4. Project Settings → API: copie el *JWT Secret* → `SUPABASE_JWT_SECRET`.
5. Authentication → Providers: deje habilitado Email (registro e inicio de sesión, RF-01/RF-02).

## 2. Local
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # complete los valores
python -m pytest -q                                     # 3 pruebas deben pasar
python -m etl.eva_etl --desde 2012                      # carga EVA real
uvicorn app.main:app --reload                           # http://127.0.0.1:8000/docs
```
Si la descarga automática falla, baje los CSV desde datos.gov.co
(2pnw-mmge y uejq-wxrr, Export → CSV) y ejecute:
`python -m etl.eva_etl --csv eva1.csv eva2.csv`

El ETL imprime las columnas que no reconozca; en ese caso ajuste `REGLAS` en `etl/eva_etl.py`.

## 3. Despliegue (Render, plan gratuito)
- New → Web Service → conecte el repositorio.
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Variables de entorno: las del `.env.example` (CORS_ORIGINS = URL del frontend).
- Verifique `https://SU-API.onrender.com/health` y `/docs`.
- Para actualizar EVA periódicamente: Render → Cron Job con `python -m etl.eva_etl`.

## 4. Endpoints
| Método | Ruta | Requisito |
|---|---|---|
| GET | /api/catalogo | selectores |
| GET | /api/presion?cultivo=&departamento= | RF-05, RF-06, RF-08 |
| GET | /api/alertas?departamento= | RF-08, RF-12 |
| POST/GET/DELETE | /api/siembras… (requiere sesión) | RF-04, RNF-03 |
| GET | /api/fuentes | RI-07 |

## 5. Supuestos a validar antes de reportar TRL 5
- Anualización: transitorios suman semestres A+B; permanentes toman el máximo. Contraste algunos
  municipios contra los informes de UPRA.
- Los datos EVA publicados llegan con rezago; la API devuelve `rezago_anios` y `es_estimacion`.
- El JWT se valida con HS256. Si su proyecto Supabase usa claves asimétricas, cambie a JWKS.
