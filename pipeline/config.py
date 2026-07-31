"""Configuration constants for the Brda weather pipeline."""

LAT = 45.997
LON = 13.526
ELEVATION = 135
TIMEZONE = "Europe/Ljubljana"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MODELS = [
    "italia_meteo_arpae_icon_2i",
    "icon_d2",
    "icon_eu",
    "ecmwf_ifs025",
    "gfs_seamless",
    "geosphere_arome_austria",
]
OPEN_METEO_HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "precipitation_probability", "weather_code", "cloud_cover",
    "wind_speed_10m", "wind_direction_10m", "uv_index",
]
OPEN_METEO_DAILY_VARS = [
    "sunrise", "sunset", "uv_index_max", "precipitation_sum",
    "weather_code", "temperature_2m_max", "temperature_2m_min",
]

# ARSO point forecast: JSON, not XML as originally assumed (verified Step 0).
ARSO_FORECAST_URL = "https://vreme.arso.gov.si/api/1.0/location/?lang=sl&location={town}"
ARSO_FORECAST_TOWN = "Nova Gorica"

# ARSO publishes all automatic stations in one JSON, timestamped to the current
# 10-minute mark (no stable "latest" alias) — fetch_obs.py computes the bucket.
ARSO_OBS_URL_TEMPLATE = (
    "https://meteo.arso.gov.si/uploads/probase/www/observ/surface/json/sl/"
    "/observationAms_si_{timestamp}.json"
)
ARSO_STATION_BILJE = "M402"        # 55m, ~13-14km from Brda (valley)
ARSO_STATION_NOVA_GORICA = "E421"  # 113m, ~9-10km from Brda (valley)

# The only station actually in Brda: a personal weather station at Vipolže,
# 45.976/13.537, ~2.5km from our point against 9-14km for the two ARSO ones.
# Logged for cross-checking the valley stations — it does not feed zdaj.
#
# Not a secret: this is the key Weather Underground ships to every visitor in
# its own page source, so it grants nothing that loading the site does not. It
# buys a documented JSON shape instead of scraping a dashboard, and can be
# rotated without warning, so a failed fetch simply yields no reading.
WU_PWS_URL = "https://api.weather.com/v2/pws/observations/current"
WU_PWS_STATION = "IBRDAM11"
WU_PWS_NAME = "VIPOLZE"
WU_PWS_WEB_KEY = "e1f10a1e78da46f5b10a1e78da96f525"

# FVG stations: training/backtest use only, never the live "zdaj" feed — their
# XML carries a 24h no-republish clause for real-time data.
FVG_OBS_URL_TEMPLATE = "https://dev.meteo.fvg.it/xml/stazioni/{code}.xml"
FVG_STATION_CAPRIVA = "CAP"   # 85m, ~5-6km from Brda
FVG_STATION_CORMONS = "N602"  # 84m, ~5-6km from Brda

# OSMER's forecast product is a qualitative regional bulletin (prose + symbol
# codes + reliability %), not per-point numeric values — can't be blended as
# a numeric model member. Logged as supplementary metadata only, not blended.
FVG_FORECAST_URL_TEMPLATE = "https://dev.meteo.fvg.it/xml/previsioni/PW{date}.xml"

RADAR_ANIM_URL = "https://meteo.arso.gov.si/uploads/probase/www/observ/radar/si0-rm-anim.gif"
SATELLITE_ANIM_URL = "https://meteo.arso.gov.si/uploads/probase/www/observ/satellite/mtg_geocolor_si-neighbours_latest.mp4"

# Hail: no per-town page exists, only a whole-Slovenia INCA probability raster,
# sampled at our coordinates. Bbox from ARSO's own INCA/SI viewer source;
# unverified against a live pixel reading — sanity-check in fetch_hail.py.
HAIL_INCA_URL_TEMPLATE = "https://vreme.arso.gov.si/api/1.0/static/inca/inca_hp_{timestamp}+0000.png"
HAIL_INCA_BBOX = (12.1, 44.657, 17.44, 47.407)  # (min_lon, min_lat, max_lon, max_lat)

PRO_VREME_URL = "https://pro-vreme.net/index.php?id=2000&m=28"
PRO_VREME_USER_AGENT = "brda-weather-app/1.0 (+https://github.com/uros-simcic/weather-app)"

# Historical training data: ARSO's own archive is login-gated (verified: op=auth
# redirect), so both training features and ground-truth targets come from
# Open-Meteo, keeping the whole backfill on one no-auth, well-documented source.
OPEN_METEO_HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
OPEN_METEO_HISTORICAL_WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
TRAINING_HISTORY_START = "2021-06-01"  # Open-Meteo's archived model coverage begins ~2021
