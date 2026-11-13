"""Lógica pura (sin base de datos): normalización y cálculo de presión de oferta (RF-08)."""
import re
import unicodedata
from datetime import date


def norm(s):
    """MAYÚSCULAS, sin tildes, espacios colapsados. Clave de búsqueda."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def calcular_presion(serie, aporte_usuarios=0.0, amarillo=1.10, rojo=1.30, anio_actual=None):
    """
    serie: lista de (anio, area_ha) del departamento, en cualquier orden.
    Índice = (área reciente EVA + aportes de usuarios) / promedio de hasta 5 años previos.
    Devuelve dict con nivel 'verde' | 'amarillo' | 'rojo' | 'sin_datos'.
    """
    anio_actual = anio_actual or date.today().year
    serie = sorted((int(a), float(v or 0)) for a, v in serie)
    if not serie:
        return {"nivel": "sin_datos", "indice": None,
                "motivo": "Sin datos EVA para este cultivo y departamento."}
    anio_rec, reciente = serie[-1]
    previos = [v for _, v in serie[:-1]][-5:]
    base = {
        "anio_reciente": anio_rec,
        "area_reciente": reciente,
        "aporte_usuarios": float(aporte_usuarios),
        "anios_promedio": len(previos),
        "rezago_anios": anio_actual - anio_rec,
        "es_estimacion": True,
    }
    if not previos or sum(previos) <= 0:
        return {**base, "nivel": "sin_datos", "indice": None, "promedio_historico": None,
                "motivo": "Historial insuficiente para calcular el promedio."}
    promedio = sum(previos) / len(previos)
    indice = (reciente + float(aporte_usuarios)) / promedio
    nivel = "rojo" if indice >= rojo else "amarillo" if indice >= amarillo else "verde"
    return {**base, "nivel": nivel, "indice": round(indice, 3),
            "promedio_historico": round(promedio, 2)}
