-- AgroData APP · esquema para Supabase (PostgreSQL + PostGIS)
create extension if not exists postgis;

-- RI-01: EVA consolidado por año (agregado desde la base municipal)
create table if not exists eva_area_anual (
  id            bigserial primary key,
  anio          int  not null,
  cod_dep       text,
  departamento  text not null,
  departamento_n text not null,   -- normalizado: MAYÚSCULAS sin tildes
  cod_mun       text,
  municipio     text,
  municipio_n   text,
  cultivo       text not null,
  cultivo_n     text not null,
  ciclo         text,
  area_sembrada numeric,
  area_cosechada numeric,
  produccion    numeric,
  fuente        text not null,
  cargado_en    timestamptz not null default now()
);
create index if not exists ix_eva_busq on eva_area_anual (cultivo_n, departamento_n, anio);
create index if not exists ix_eva_anio on eva_area_anual (anio);

-- Serie departamental usada por las alertas
create or replace view eva_depto as
select anio, cultivo_n, min(cultivo) as cultivo,
       departamento_n, min(departamento) as departamento,
       sum(area_sembrada) as area, max(fuente) as fuente
from eva_area_anual
group by anio, cultivo_n, departamento_n;

-- RF-04: intenciones y siembras registradas por los usuarios
create table if not exists siembras (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null,
  cultivo       text not null,
  cultivo_n     text not null,
  departamento  text not null,
  departamento_n text not null,
  municipio     text,
  area_ha       numeric not null check (area_ha > 0),
  fecha_siembra date,
  tipo          text not null check (tipo in ('planeada','establecida')),
  creado_en     timestamptz not null default now()
);
create index if not exists ix_siembras_busq on siembras (cultivo_n, departamento_n);
alter table siembras enable row level security;
drop policy if exists siembras_propias on siembras;
create policy siembras_propias on siembras using (user_id = auth.uid());

-- RI-07: metadatos de actualización de las fuentes
create table if not exists etl_log (
  id           bigserial primary key,
  fuente       text not null,
  url          text,
  filas        int,
  anio_min     int,
  anio_max     int,
  ejecutado_en timestamptz not null default now()
);
