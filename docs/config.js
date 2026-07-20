// Frontend configuration constants for the Brda weather app.

export const COORDS = { lat: 45.997, lon: 13.526, elevation: 135 };

export const RADAR_ANIM_URL = "https://meteo.arso.gov.si/uploads/probase/www/observ/radar/si0-rm-anim.gif";
export const SATELLITE_ANIM_URL = "https://meteo.arso.gov.si/uploads/probase/www/observ/satellite/mtg_geocolor_si-neighbours_latest.mp4";

export const REFRESH_INTERVAL_MS = 30 * 60 * 1000;

// Six cross-check buttons, exact order and casing per spec §4.4.
export const CROSS_CHECK_LINKS = [
  { label: "pro-vreme", href: "https://pro-vreme.net/index.php?id=2000&m=28" },
  { label: "ARSO", href: "https://vreme.arso.gov.si/napoved/Nova%20Gorica/graf/0" },
  { label: "meteo.it", href: "https://www.meteo.it/meteo/dolegna-del-collio-31004" },
  { label: "bergfex", href: "https://www.bergfex.com/sommer/brda/wetter/" },
  { label: "yr.no", href: "https://www.yr.no/en/forecast/daily-table/2-3239083/Slovenia/Brda/Municipality%20of%20Brda" },
  { label: "windy", href: "https://www.windy.com/45.997/13.526?ecmwf,45.997,13.526,10" },
];
