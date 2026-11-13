import pandas as pd
from app.core import calcular_presion, norm
from etl.eva_etl import transformar


def test_norm():
    assert norm("  Boyacá  ") == "BOYACA"
    assert norm("Cebolla de bulbo") == "CEBOLLA DE BULBO"


def test_semaforo():
    serie = [(2019, 100), (2020, 100), (2021, 100), (2022, 100), (2023, 100), (2024, 125)]
    assert calcular_presion(serie, 0, anio_actual=2026)["nivel"] == "amarillo"
    assert calcular_presion(serie, 0, anio_actual=2026)["rezago_anios"] == 2
    assert calcular_presion(serie, 10, anio_actual=2026)["nivel"] == "rojo"      # (125+10)/100 = 1.35
    assert calcular_presion([(2024, 50)], 0)["nivel"] == "sin_datos"
    assert calcular_presion([], 0)["nivel"] == "sin_datos"


def test_etl_transitorio_suma_semestres_y_permanente_toma_maximo():
    df = pd.DataFrame({
        "CÓD. \nDEP.": ["25"] * 4, "DEPARTAMENTO": ["CUNDINAMARCA"] * 4,
        "CÓD. \nMUN.": ["25269"] * 4, "MUNICIPIO": ["FACATATIVÁ"] * 4,
        "CULTIVO": ["PAPA", "PAPA", "AGUACATE", "AGUACATE"],
        "AÑO": ["2022"] * 4, "PERIODO": ["2022A", "2022B", "2022A", "2022B"],
        "Área Sembrada\n(ha)": ["10", "5,5", "20", "20"],
        "CICLO DE CULTIVO": ["TRANSITORIO", "TRANSITORIO", "PERMANENTE", "PERMANENTE"],
    })
    out = transformar(df, "prueba").set_index("cultivo")
    assert out.loc["PAPA", "area_sembrada"] == 15.5
    assert out.loc["AGUACATE", "area_sembrada"] == 20
    assert out.loc["PAPA", "departamento_n"] == "CUNDINAMARCA"
