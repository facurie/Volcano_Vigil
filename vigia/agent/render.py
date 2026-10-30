"""Bulletins as Markdown (one language) and HTML (both), and the files a bulletin is published as.

Times show in the volcano's local time with its UTC offset. In HTML every text the model wrote is escaped.
"""

from __future__ import annotations

import html
import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from vigia.timeutil import parse_utc

if TYPE_CHECKING:
    from vigia.agent.bulletin import Bulletin, CitedMeasurement

Lang = Literal["en", "es"]
LEVELS = {  # activity level: (English, Spanish); what the cameras show, never an alert level
    "no_view": ("No usable view", "Sin vista útil"),
    "quiet": ("No visible activity", "Sin actividad visible"),
    "degassing": ("Gas or steam plume", "Columna de gas o vapor"),
    "incandescence": ("Glowing lava, no fountain", "Lava incandescente, sin fuente"),
    "fountaining": ("Lava fountain", "Fuente de lava"),
}
TARGETS = {"plume": ("plume", "columna"), "fountain": ("lava fountain", "fuente de lava"),
           "incandescence": ("glow", "incandescencia")}
METRICS = {
    "top_height": ("top above the vent", "tope sobre la boca"),
    "top_altitude": ("top above sea level", "tope sobre el nivel del mar"),
    "area": ("area", "área"),
    "drift_offset": ("drift across the line of sight", "deriva transversal a la visual"),
    "drift_bearing": ("side of the line of sight", "lado de la visual"),
}
WORDS = {
    "activity": ("Activity", "Actividad"), "measurements": ("Measurements", "Mediciones"),
    "what": ("What", "Qué"), "camera": ("Camera", "Cámara"), "value": ("Value", "Valor"),
    "captured": ("Captured", "Captura"), "frames": ("Frames", "Cuadros"), "checked": ("Checked", "Verificado"),
    "yes": ("yes", "sí"), "no": ("no", "no"), "wind": ("Wind", "Viento"), "evidence": ("Evidence", "Evidencia"),
    "notes": ("Notes", "Notas"), "official": ("Official source", "Fuente oficial"),
}
STYLE = ("body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
         ".disclaimer{background:#fff4d6;border-left:4px solid #e0a800;padding:.6rem .8rem}"
         "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}"
         "img{max-width:100%}article+article{border-top:2px solid #ddd;margin-top:2rem}")


def _pick(pair: tuple[str, str], lang: Lang) -> str:
    return pair[0] if lang == "en" else pair[1]


def local_time(utc: str, offset_hours: float | None) -> str:
    """'2026-10-17 04:55 (UTC-10)': a UTC time in the volcano's local time; in UTC when it has no offset."""
    when = parse_utc(utc)
    if offset_hours is None:
        return f"{when:%Y-%m-%d %H:%M} UTC"
    return f"{when + timedelta(hours=offset_hours):%Y-%m-%d %H:%M} (UTC{offset_hours:+g})"


def number(value: float, lang: Lang, decimals: int = 0) -> str:
    """6,951.5 in English, 6.951,5 in Spanish."""
    text = f"{value:,.{decimals}f}"
    return text if lang == "en" else text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def quantity(m: CitedMeasurement, lang: Lang) -> str:
    if m.unit == "deg":
        return f"{number(m.value, lang)}° ± {number(m.sigma, lang)}°"
    return f"{number(m.value, lang)} ± {number(m.sigma, lang)} {'m²' if m.unit == 'm2' else 'm'}"


def wind_text(b: Bulletin, lang: Lang) -> str:
    """The run's wind check in one language."""
    layer, check = b.wind["layer_mean"], b.wind["drift_check"]
    hour = local_time(b.wind["model_hour"], b.utc_offset_hours)
    low, high = number(layer["bottom_m"], lang), number(layer["top_m"], lang)
    speed = number(layer["speed_ms"], lang, 1)
    side, angle = number(check["measured_side_deg"], lang), number(check["angle_deg"], lang)
    if lang == "en":
        verdict = {True: "consistent", False: "not consistent", None: "too calm to tell"}[check["consistent"]]
        return (f"Model wind ({b.wind['source']}, {hour}): between {low} and {high} m it blows from "
                f"{layer['from_deg']}° toward {layer['toward_deg']}° at {speed} m/s. The plume was seen on the "
                f"{side}° side of the camera's line of sight, {angle}° from where the wind blows: {verdict}.")
    verdict = {True: "coherente", False: "no coherente",
               None: "viento demasiado calmo para juzgar"}[check["consistent"]]
    return (f"Viento del modelo ({b.wind['source']}, {hour}): entre {low} y {high} m sopla desde "
            f"{layer['from_deg']}° hacia {layer['toward_deg']}° a {speed} m/s. La columna se vio del lado de {side}° "
            f"de la visual de la cámara, a {angle}° de hacia donde sopla el viento: {verdict}.")


def _texts(b: Bulletin, lang: Lang) -> tuple[str, str, str]:
    if lang == "en":
        return b.headline_en, b.body_en, b.disclaimer_en
    return b.headline_es, b.body_es, b.disclaimer_es


def _header(lang: Lang) -> list[str]:
    return [_pick(WORDS[key], lang) for key in ("what", "camera", "value", "captured", "frames", "checked")]


def _rows(b: Bulletin, lang: Lang) -> list[list[str]]:
    rows = []
    for m in b.measurements:
        captured = local_time(m.captured_at, b.utc_offset_hours) if m.captured_at else "–"
        rows.append([f"{_pick(TARGETS[m.target], lang)}: {_pick(METRICS[m.metric], lang)}", m.camera_id,
                     quantity(m, lang), captured, ", ".join(map(str, m.frame_ids)),
                     _pick(WORDS["yes" if m.verified else "no"], lang)])
    return rows


def _cell(text: str) -> str:
    """A Markdown table cell: a pipe or a line break in it would break the table."""
    return " ".join(text.replace("|", "\\|").split())


def to_markdown(b: Bulletin, lang: Lang, *, image_root: str = "") -> str:
    """The bulletin in one language; each evidence image links to image_root plus its data-dir path."""
    headline, body, disclaimer = _texts(b, lang)
    level = _pick(LEVELS[b.activity_level], lang)
    when = local_time(b.clock, b.utc_offset_hours)
    lines = [f"# {headline}", "", f"{b.volcano_name} · {when} · {_pick(WORDS['activity'], lang)}: {level}", "",
             f"> **{disclaimer}**", "", body, ""]
    if b.measurements:
        lines += [f"## {_pick(WORDS['measurements'], lang)}", "", "| " + " | ".join(_header(lang)) + " |",
                  "|---|---|---|---|---|---|"]
        lines += ["| " + " | ".join(map(_cell, row)) + " |" for row in _rows(b, lang)] + [""]
    if b.wind:
        lines += [f"## {_pick(WORDS['wind'], lang)}", "", wind_text(b, lang), ""]
    if b.evidence:
        lines += [f"## {_pick(WORDS['evidence'], lang)}", ""]
        for e in b.evidence:
            caption = e.caption_en if lang == "en" else e.caption_es
            alt = caption.replace("[", "(").replace("]", ")")
            lines += [f"![{alt}]({image_root}{e.overlay})", "",
                      f"*{caption}* ({e.camera_id}, {local_time(e.captured_at, b.utc_offset_hours)})", ""]
    if b.notes:
        lines += [f"## {_pick(WORDS['notes'], lang)}", ""] + [f"- {note}" for note in b.notes] + [""]
    lines.append(f"{_pick(WORDS['official'], lang)}: [{b.official_agency}]({b.official_url})")
    return "\n".join(lines) + "\n"


def _article(b: Bulletin, lang: Lang, image_root: str) -> str:
    e = html.escape
    headline, body, disclaimer = _texts(b, lang)
    level = _pick(LEVELS[b.activity_level], lang)
    parts = [f'<article lang="{lang}">', f'<p class="disclaimer">{e(disclaimer)}</p>', f"<h1>{e(headline)}</h1>",
             f"<p>{e(b.volcano_name)} · {e(local_time(b.clock, b.utc_offset_hours))} · "
             f"{_pick(WORDS['activity'], lang)}: {e(level)}</p>"]
    parts += [f"<p>{e(paragraph.strip())}</p>" for paragraph in body.split("\n\n") if paragraph.strip()]
    if b.measurements:
        parts += [f"<h2>{_pick(WORDS['measurements'], lang)}</h2>", "<table>",
                  "<tr>" + "".join(f"<th>{e(cell)}</th>" for cell in _header(lang)) + "</tr>"]
        parts += ["<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in _rows(b, lang)]
        parts.append("</table>")
    if b.wind:
        parts += [f"<h2>{_pick(WORDS['wind'], lang)}</h2>", f"<p>{e(wind_text(b, lang))}</p>"]
    if b.evidence:
        parts.append(f"<h2>{_pick(WORDS['evidence'], lang)}</h2>")
        for item in b.evidence:
            caption = item.caption_en if lang == "en" else item.caption_es
            when = local_time(item.captured_at, b.utc_offset_hours)
            parts.append(f'<figure><img src="{e(image_root + item.overlay)}" alt="{e(caption)}">'
                         f"<figcaption>{e(caption)} ({e(item.camera_id)}, {e(when)})</figcaption></figure>")
    if b.notes:
        parts += [f"<h2>{_pick(WORDS['notes'], lang)}</h2>", "<ul>"]
        parts += [f"<li>{e(note)}</li>" for note in b.notes] + ["</ul>"]
    parts += [f'<p>{_pick(WORDS["official"], lang)}: <a href="{e(b.official_url)}">{e(b.official_agency)}</a></p>',
              "</article>"]
    return "\n".join(parts)


def to_html(b: Bulletin, *, image_root: str = "") -> str:
    """The bulletin as one HTML page, English then Spanish."""
    articles = "\n".join(_article(b, lang, image_root) for lang in ("en", "es"))
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{html.escape(b.headline_en)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n{articles}\n"
            "</body>\n</html>\n")


def publish(b: Bulletin, data_dir: Path, out_dir: Path) -> Path:
    """Write bulletin.html, bulletin.en.md and bulletin.es.md into out_dir/run<run id>; returns that folder."""
    folder = out_dir / f"run{b.run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    root = Path(os.path.relpath(data_dir, folder)).as_posix() + "/"
    (folder / "bulletin.html").write_text(to_html(b, image_root=root), encoding="utf-8")
    for lang in ("en", "es"):
        (folder / f"bulletin.{lang}.md").write_text(to_markdown(b, lang, image_root=root), encoding="utf-8")
    return folder
