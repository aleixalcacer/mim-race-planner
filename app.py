from datetime import datetime
import math
import xml.etree.ElementTree as ET

import altair as alt
import pandas as pd
import streamlit as st


START_TIME_STR = "06:00"
START_MINUTES = 6 * 60
N_PEER_RUNNERS = 20
TIEMPOS_PATH = "data/mim_tiempos.csv"
AVITUALLAMIENTOS_PATH = "data/avituallamientos.csv"
GPX_PATH = "data/MiM.gpx"
RACE_DISTANCE_KM = 60.0


# ---------------------------------------------------------------------------
# Utilidades de tiempo y ritmo
# ---------------------------------------------------------------------------

def hhmm_to_minutes(value: str) -> int:
    dt = datetime.strptime(value.strip(), "%H:%M")
    return dt.hour * 60 + dt.minute


def minutes_to_hhmm(minutes_from_midnight: int) -> str:
    day_offset = minutes_from_midnight // (24 * 60)
    day_minutes = minutes_from_midnight % (24 * 60)
    hh = day_minutes // 60
    mm = day_minutes % 60
    suffix = " (+1d)" if day_offset > 0 else ""
    return f"{hh:02d}:{mm:02d}{suffix}"


def elapsed_from_start(clock_minutes: int) -> int:
    elapsed = clock_minutes - START_MINUTES
    if elapsed < 0:
        elapsed += 24 * 60
    return elapsed


def duration_to_minutes(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Formato no válido")

    hours, minutes = parts
    if not (hours.isdigit() and minutes.isdigit()):
        raise ValueError("Formato no válido")

    hours_int = int(hours)
    minutes_int = int(minutes)
    if minutes_int < 0 or minutes_int >= 60:
        raise ValueError("Formato no válido")

    total = hours_int * 60 + minutes_int
    if total <= 0:
        raise ValueError("Duración no válida")

    return total


def pace_to_text(minutes_per_km: float) -> str:
    if pd.isna(minutes_per_km) or minutes_per_km <= 0:
        return "-"
    total_seconds = int(round(minutes_per_km * 60))
    pace_min = total_seconds // 60
    pace_sec = total_seconds % 60
    return f"{pace_min:02d}:{pace_sec:02d}"


# ---------------------------------------------------------------------------
# Utilidades geográficas
# ---------------------------------------------------------------------------

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a_val = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c_val = 2 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))
    return earth_radius_m * c_val


# ---------------------------------------------------------------------------
# Carga de datos (cacheada)
# ---------------------------------------------------------------------------

@st.cache_data
def load_gpx_profile(gpx_path: str = GPX_PATH) -> pd.DataFrame:
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}

    track_points = root.findall(".//gpx:trkpt", namespace)
    if not track_points:
        track_points = root.findall(".//trkpt")

    rows: list[dict[str, float]] = []
    previous_lat = None
    previous_lon = None
    accumulated_distance_m = 0.0

    for point in track_points:
        lat_attr = point.attrib.get("lat")
        lon_attr = point.attrib.get("lon")
        if lat_attr is None or lon_attr is None:
            continue

        try:
            latitude = float(lat_attr)
            longitude = float(lon_attr)
        except ValueError:
            continue

        elevation_node = point.find("gpx:ele", namespace)
        if elevation_node is None:
            elevation_node = point.find("ele")
        if elevation_node is None or elevation_node.text is None:
            continue

        try:
            elevation = float(elevation_node.text)
        except ValueError:
            continue

        if previous_lat is not None and previous_lon is not None:
            accumulated_distance_m += haversine_meters(
                previous_lat, previous_lon, latitude, longitude
            )

        rows.append({"Distancia km": accumulated_distance_m / 1000, "Elevación m": elevation})
        previous_lat = latitude
        previous_lon = longitude

    if len(rows) < 2:
        return pd.DataFrame(columns=["Distancia km", "Elevación m"])

    gpx_df = pd.DataFrame(rows)
    raw_total_km = float(gpx_df["Distancia km"].iloc[-1])
    if raw_total_km > 0:
        gpx_df["Distancia km"] = gpx_df["Distancia km"] * (RACE_DISTANCE_KM / raw_total_km)

    return gpx_df


@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    tiempos = pd.read_csv(TIEMPOS_PATH, sep=";")
    avitu = pd.read_csv(AVITUALLAMIENTOS_PATH, sep=";")
    return tiempos, avitu


# ---------------------------------------------------------------------------
# Construcción del dataset de perfil histórico
# ---------------------------------------------------------------------------

def build_profile_dataset(
    tiempos: pd.DataFrame, controls: list[str], finish_control: str
) -> pd.DataFrame:
    rows = []

    for _, row in tiempos.iterrows():
        finish_value = row.get(finish_control)
        if pd.isna(finish_value):
            continue

        try:
            finish_elapsed = elapsed_from_start(hhmm_to_minutes(str(finish_value)))
        except ValueError:
            continue

        if finish_elapsed <= 0:
            continue

        profile_row: dict = {"finish_elapsed": finish_elapsed}
        valid_row = True

        for control in controls:
            control_value = row.get(control)
            if pd.isna(control_value):
                valid_row = False
                break

            try:
                control_elapsed = elapsed_from_start(hhmm_to_minutes(str(control_value)))
            except ValueError:
                valid_row = False
                break

            if control_elapsed < 0 or control_elapsed > finish_elapsed:
                valid_row = False
                break

            profile_row[control] = control_elapsed / finish_elapsed

        if valid_row:
            rows.append(profile_row)

    if not rows:
        return pd.DataFrame(columns=["finish_elapsed", *controls])

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Cálculo del plan de carrera
# ---------------------------------------------------------------------------

def compute_plan(
    tiempos_df: pd.DataFrame,
    avitu_df: pd.DataFrame,
    target_elapsed: int,
) -> pd.DataFrame:
    controls = avitu_df["Control"].dropna().tolist()
    finish_control = controls[-1]

    profile_df = build_profile_dataset(tiempos_df, controls, finish_control)
    if profile_df.empty:
        return pd.DataFrame()

    profile_df = profile_df.copy()
    profile_df["distance_to_target"] = (profile_df["finish_elapsed"] - target_elapsed).abs()
    nearest_df = profile_df.nsmallest(N_PEER_RUNNERS, "distance_to_target")

    estimated_elapsed_df = nearest_df[controls].mul(target_elapsed)
    median_elapsed = estimated_elapsed_df.median(numeric_only=True)
    std_elapsed = estimated_elapsed_df.std(numeric_only=True).fillna(0)

    segment_elapsed_df = estimated_elapsed_df.diff(axis=1)
    segment_elapsed_df.iloc[:, 0] = estimated_elapsed_df.iloc[:, 0]
    median_segment = segment_elapsed_df.median(numeric_only=True)
    std_segment = segment_elapsed_df.std(numeric_only=True).fillna(0)

    plan = avitu_df[["Control", "KM", "D+", "d+", "Asistencia", "Retirada"]].copy()
    plan = plan[plan["Control"].isin(median_elapsed.index)].copy()
    plan["KM"] = pd.to_numeric(plan["KM"], errors="coerce")
    plan["D+"] = pd.to_numeric(plan["D+"], errors="coerce")
    plan["d+"] = pd.to_numeric(plan["d+"], errors="coerce")
    plan["KM tramo"] = plan["KM"].diff().fillna(plan["KM"])

    plan["Min acumulados"] = plan["Control"].map(median_elapsed).round().astype(int)
    plan["Std acumulados"] = plan["Control"].map(std_elapsed).round().fillna(0).astype(int)
    plan["Hora paso"] = plan["Min acumulados"].apply(
        lambda m: minutes_to_hhmm(START_MINUTES + m)
    )
    plan["Tiempo acumulado"] = plan["Min acumulados"].apply(
        lambda m: f"{m // 60:02d}:{m % 60:02d}"
    )
    plan["Min tramo"] = plan["Control"].map(median_segment).round().astype(int)
    plan["Std tramo"] = plan["Control"].map(std_segment).round().fillna(0).astype(int)
    plan["Tiempo tramo"] = plan["Min tramo"].apply(
        lambda m: f"{m // 60:02d}:{m % 60:02d}"
    )

    segment_pace_df = segment_elapsed_df.divide(plan.set_index("Control")["KM tramo"], axis=1)
    plan["Min/km mediana valor"] = plan["Control"].map(segment_pace_df.median(numeric_only=True))
    plan["Min/km p10"] = plan["Control"].map(segment_pace_df.quantile(0.10, numeric_only=True))
    plan["Min/km p90"] = plan["Control"].map(segment_pace_df.quantile(0.90, numeric_only=True))
    plan["Min/km tramo"] = plan["Min/km mediana valor"].apply(pace_to_text)

    plan["Control anterior"] = plan["Control"].shift(1).fillna("Salida")
    plan["Tramo"] = plan["Control anterior"] + " - " + plan["Control"]

    return plan


# ---------------------------------------------------------------------------
# Construcción del gráfico Altair
# ---------------------------------------------------------------------------

def build_chart(plan: pd.DataFrame, gpx_profile_df: pd.DataFrame) -> alt.Chart:
    chart_df = plan[
        [
            "Control", "Control anterior", "Tramo", "Tiempo tramo", "Min/km tramo",
            "KM", "KM tramo", "Min/km mediana valor", "Min/km p10", "Min/km p90",
            "D+", "Hora paso",
        ]
    ].copy()

    start_row = pd.DataFrame([{
        "Control": "Salida", "Control anterior": pd.NA, "Tramo": pd.NA,
        "Tiempo tramo": pd.NA, "Min/km tramo": pd.NA, "KM": 0.0, "KM tramo": pd.NA,
        "Min/km mediana valor": pd.NA, "Min/km p10": pd.NA, "Min/km p90": pd.NA,
        "D+": pd.NA, "Hora paso": START_TIME_STR,
    }])
    chart_df = pd.concat([start_row, chart_df], ignore_index=True)
    chart_df = chart_df.sort_values("KM").reset_index(drop=True)

    control_markers_df = (
        chart_df[["Control", "KM", "D+", "Hora paso"]]
        .dropna(subset=["KM", "Hora paso"])
        .drop_duplicates()
        .copy()
    )
    control_markers_df["X km"] = control_markers_df["KM"]
    if not (control_markers_df["Control"] == "Salida").any():
        control_markers_df = pd.concat(
            [
                pd.DataFrame([{
                    "Control": "Salida", "KM": 0.0, "D+": 0.0,
                    "X km": 0.0, "Hora paso": START_TIME_STR,
                }]),
                control_markers_df,
            ],
            ignore_index=True,
        )

    pace_df = chart_df.dropna(subset=["Min/km mediana valor", "Min/km p10", "Min/km p90"]).copy()
    pace_df["X km"] = pace_df["KM"] - (pace_df["KM tramo"] / 2)

    pace_min = float(pace_df["Min/km p10"].min())
    pace_max = float(pace_df["Min/km p90"].max())
    pace_span = max(pace_max - pace_min, 0.2)
    pace_padding = pace_span * 0.08
    pace_domain = [pace_min - pace_padding, pace_max + pace_padding]

    pace_base = alt.Chart(pace_df).encode(
        x=alt.X("X km:Q", title="Distancia acumulada (km)", scale=alt.Scale(domainMin=0)),
        tooltip=[
            alt.Tooltip("Tramo:N", title="Tramo"),
            alt.Tooltip("KM tramo:Q", title="Distancia", format=".1f"),
            alt.Tooltip("Min/km tramo:N", title="Ritmo medio"),
            alt.Tooltip("Tiempo tramo:N", title="Tiempo tramo"),
        ],
    )
    pace_band = pace_base.mark_area(opacity=0.1, color="#8b0000").encode(
        y=alt.Y(
            "Min/km p10:Q",
            title="Ritmo tramo (min/km)",
            axis=alt.Axis(titleColor="#8b0000"),
            scale=alt.Scale(domain=pace_domain[::-1], zero=False, nice=False),
        ),
        y2="Min/km p90:Q",
    )
    pace_line = pace_base.mark_line(point=alt.OverlayMarkDef(color="#8b0000"), color="#8b0000", size=3).encode(
        y=alt.Y(
            "Min/km mediana valor:Q",
            title="Ritmo tramo (min/km)",
            axis=alt.Axis(titleColor="#8b0000"),
            scale=alt.Scale(domain=pace_domain[::-1], zero=False, nice=False),
        ),
    )

    control_base = alt.Chart(control_markers_df).encode(
        x=alt.X("X km:Q"),
        tooltip=[
            alt.Tooltip("Control:N", title="Control"),
            alt.Tooltip("KM:Q", title="KM", format=".1f"),
            alt.Tooltip("Hora paso:N", title="Hora paso"),
        ],
    )
    control_vlines = control_base.mark_rule(opacity=1, color="#e63946").encode(
        y=alt.datum(0, axis=None),
        y2=alt.datum(1),
        size=alt.SizeValue(7),
    )
    control_labels = control_base.mark_text(
        angle=270, align="left", dx=10, color="#c0001a", fontWeight="bold"
    ).encode(
        y=alt.datum(1, axis=None),
        text="Control:N",
    )

    if gpx_profile_df.empty:
        return (control_vlines + pace_band + pace_line).resolve_scale(y="independent")

    gpx_df = gpx_profile_df.copy()
    gpx_df["X km"] = gpx_df["Distancia km"]
    gpx_area = (
        alt.Chart(gpx_df)
        .encode(
            x=alt.X("X km:Q", title="Distancia acumulada (km)", scale=alt.Scale(domainMin=0)),
            tooltip=[],
        )
        .mark_area(opacity=0.20, color="#e63946")
        .encode(
            y=alt.Y(
                "Elevación m:Q",
                title="Elevación (m)",
                axis=alt.Axis(orient="right", titleColor="#e63946"),
            ),
        )
    )

    return (gpx_area + control_vlines + control_labels + pace_line + pace_band).resolve_scale(
        y="independent"
    )


# ---------------------------------------------------------------------------
# Interfaz Streamlit
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="MiM | Tu estrategia de carrera", layout="wide")
    st.title("⛰️ MiM | Tu estrategia de carrera")
    st.caption("Calcula a qué hora deberías pasar por cada punto para cumplir tu objetivo.")

    try:
        tiempos_df, avitu_df = load_data()
    except FileNotFoundError as exc:
        st.error(f"No se ha encontrado el archivo: {exc}")
        return

    controls = avitu_df["Control"].dropna().tolist()
    missing_controls = [c for c in controls if c not in tiempos_df.columns]
    if missing_controls:
        st.error(f"Faltan columnas de control en mim_tiempos.csv: {', '.join(missing_controls)}")
        return

    st.subheader("🎯 Tu objetivo")
    st.caption("Define el tiempo total con el que quieres completar la carrera.")
    target_duration_str = st.text_input(
        "Tiempo total objetivo (HH:MM)",
        value="08:00",
        help="Introduce cuánto tiempo tardarás en completar la carrera.",
    )

    try:
        target_elapsed = duration_to_minutes(target_duration_str)
    except ValueError:
        st.error("Formato no válido. Usa HH:MM para duración (por ejemplo, 08:30).")
        return

    plan = compute_plan(tiempos_df, avitu_df, target_elapsed)
    if plan.empty:
        st.error("No hay datos históricos válidos suficientes para calcular la estimación.")
        return

    col_start, col_finish = st.columns(2)
    col_start.metric("Salida", START_TIME_STR)
    col_finish.metric("Llegada a meta (objetivo)", minutes_to_hhmm(START_MINUTES + target_elapsed))

    st.subheader("🗺️ Tu estrategia de carrera")
    st.caption(
        f"Visualiza tu plan con el perfil de elevación y el ritmo recomendado por tramo. "
        f"Datos basados en los {N_PEER_RUNNERS} corredores más cercanos a tu objetivo. "
        f"Si pasas el cursor por cada tramo o control, verás información detallada sobre tiempos y ritmos."
    )

    try:
        gpx_profile_df = load_gpx_profile()
    except FileNotFoundError:
        st.info(f"No se encontró el fichero {GPX_PATH} en la carpeta del proyecto.")
        gpx_profile_df = pd.DataFrame(columns=["Distancia km", "Elevación m"])
    except ET.ParseError:
        st.error(f"No se pudo parsear el fichero {GPX_PATH}. Revisa que sea un GPX válido.")
        gpx_profile_df = pd.DataFrame(columns=["Distancia km", "Elevación m"])
    else:
        if gpx_profile_df.empty:
            st.warning("No hay suficientes puntos con elevación en el GPX para dibujar el perfil.")

    st.altair_chart(build_chart(plan, gpx_profile_df), use_container_width=True)

    with st.expander("📊 Desglose detallado por tramo"):
        export_df = plan[
            [
                "Tramo", "KM", "D+", "Hora paso", "Tiempo acumulado",
                "KM tramo", "d+", "Tiempo tramo", "Min/km tramo", "Min/km p10", "Min/km p90",
            ]
        ].copy()
        export_df.columns = [
            "Tramo", "KM Acumulado", "D+ Acumulado", "Hora de Paso", "Tiempo Acumulado",
            "KM Tramo", "D+ Tramo", "Tiempo Tramo", "Ritmo (min/km)", "Ritmo p10", "Ritmo p90",
        ]
        export_df["Ritmo p10"] = export_df["Ritmo p10"].apply(pace_to_text)
        export_df["Ritmo p90"] = export_df["Ritmo p90"].apply(pace_to_text)

        st.dataframe(
            export_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "KM Acumulado": st.column_config.NumberColumn(format="%.1f km", label="Distancia"),
                "KM Tramo": st.column_config.NumberColumn(format="%.1f km", label="Dist. Tramo"),
                "D+ Acumulado": st.column_config.NumberColumn(format="%.0f m", label="Desnivel +"),
                "D+ Tramo": st.column_config.NumberColumn(format="%.0f m", label="D+ Tramo"),
                "Ritmo (min/km)": st.column_config.TextColumn(),
                "Ritmo p10": st.column_config.TextColumn(),
                "Ritmo p90": st.column_config.TextColumn(),
            },
        )

        st.download_button(
            label="📥 Descargar plan como CSV",
            data=export_df.to_csv(index=False, sep=";"),
            file_name="plan_carrera_MIM.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
