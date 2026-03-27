# ⛰️ MiM | Estrategia de carrera

Calculadora de estrategia de carrera para la **Marató i Mitja** (60 km, 3.356 m D+).

Introduce tu tiempo objetivo y la app te calcula a qué hora deberías pasar por cada avituallamiento, basándose en los ritmos de corredores con un resultado similar en ediciones anteriores.

## Cómo funciona

1. Introduce tu tiempo objetivo en formato `HH:MM`
2. La app busca los 20 corredores históricos más cercanos a ese tiempo
3. Calcula la mediana de sus repartos de esfuerzo por tramo
4. Muestra el plan sobre el perfil de elevación del recorrido

## Avituallamentos

| Control | KM | D+ acum. |
|---|---|---|
| Borriol | 8,4 | 362 m |
| Bassa | 22,9 | 1.081 m |
| Useres | 31,5 | 1.540 m |
| Torrosselles | 41,1 | 2.092 m |
| Xodos | 50,1 | 2.753 m |
| Banyadera | 56,8 | 3.336 m |
| Sant Joan (meta) | 60,0 | 3.356 m |

## Uso local

Requiere Python 3.12+ y [uv](https://docs.astral.sh/uv/).

```bash
uv run streamlit run app.py
```

## Deploy

La app está desplegada en Streamlit Cloud.
