"""Bulletins as Markdown and HTML, and the files a bulletin is published as.

Times show in the volcano's local time with its UTC offset. In HTML every text the model wrote is escaped.
"""

from __future__ import annotations

import html
import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from vigil.timeutil import parse_utc

if TYPE_CHECKING:
    from vigil.agent.bulletin import Bulletin, CitedMeasurement

LEVELS = {  # activity level: what the cameras show, never an alert level
    "no_view": "No usable view",
    "quiet": "No visible activity",
    "degassing": "Gas or steam plume",
    "incandescence": "Glowing lava, no fountain",
    "fountaining": "Lava fountain",
}
TARGETS = {"plume": "plume", "fountain": "lava fountain", "incandescence": "glow"}
METRICS = {
    "top_height": "top above the vent",
    "top_altitude": "top above sea level",
    "area": "area",
    "drift_offset": "drift across the line of sight",
    "drift_bearing": "side of the line of sight",
}
TABLE_HEADER = ["What", "Camera", "Value", "Captured", "Frames", "Checked"]
LEGACY_FILES = ("bulletin.en.md", "bulletin.es.md")  # what a bulletin was published as before Phase 9
STYLE = ("body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
         ".disclaimer{background:#fff4d6;border-left:4px solid #e0a800;padding:.6rem .8rem}"
         "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}"
         "img{max-width:100%}")


def local_time(utc: str, offset_hours: float | None) -> str:
    """'2026-10-17 04:55 (UTC-10)': a UTC time in the volcano's local time; in UTC when it has no offset."""
    when = parse_utc(utc)
    if offset_hours is None:
        return f"{when:%Y-%m-%d %H:%M} UTC"
    return f"{when + timedelta(hours=offset_hours):%Y-%m-%d %H:%M} (UTC{offset_hours:+g})"


def number(value: float, decimals: int = 0) -> str:
    """6,951.5"""
    return f"{value:,.{decimals}f}"


def quantity(m: CitedMeasurement) -> str:
    if m.unit == "deg":
        return f"{number(m.value)}° ± {number(m.sigma)}°"
    return f"{number(m.value)} ± {number(m.sigma)} {'m²' if m.unit == 'm2' else 'm'}"


def wind_text(b: Bulletin) -> str:
    """The run's wind check in a sentence."""
    layer, check = b.wind["layer_mean"], b.wind["drift_check"]
    hour = local_time(b.wind["model_hour"], b.utc_offset_hours)
    low, high = number(layer["bottom_m"]), number(layer["top_m"])
    speed = number(layer["speed_ms"], 1)
    side, angle = number(check["measured_side_deg"]), number(check["angle_deg"])
    verdict = {True: "consistent", False: "not consistent", None: "too calm to tell"}[check["consistent"]]
    return (f"Model wind ({b.wind['source']}, {hour}): between {low} and {high} m it blows from "
            f"{layer['from_deg']}° toward {layer['toward_deg']}° at {speed} m/s. The plume was seen on the "
            f"{side}° side of the camera's line of sight, {angle}° from where the wind blows: {verdict}.")


def table_rows(b: Bulletin) -> list[list[str]]:
    rows = []
    for m in b.measurements:
        captured = local_time(m.captured_at, b.utc_offset_hours) if m.captured_at else "–"
        rows.append([f"{TARGETS[m.target]}: {METRICS[m.metric]}", m.camera_id, quantity(m), captured,
                     ", ".join(map(str, m.frame_ids)), "yes" if m.verified else "no"])
    return rows


def _cell(text: str) -> str:
    """A Markdown table cell: a pipe or a line break in it would break the table."""
    return " ".join(text.replace("|", "\\|").split())


def to_markdown(b: Bulletin, *, image_root: str = "") -> str:
    """The bulletin; each evidence image links to image_root plus its data-dir path."""
    level = LEVELS[b.activity_level]
    when = local_time(b.clock, b.utc_offset_hours)
    lines = [f"# {b.headline}", "", f"{b.volcano_name} · {when} · Activity: {level}", "",
             f"> **{b.disclaimer}**", "", b.body, ""]
    if b.measurements:
        lines += ["## Measurements", "", "| " + " | ".join(TABLE_HEADER) + " |", "|---|---|---|---|---|---|"]
        lines += ["| " + " | ".join(map(_cell, row)) + " |" for row in table_rows(b)] + [""]
    if b.wind:
        lines += ["## Wind", "", wind_text(b), ""]
    if b.evidence:
        lines += ["## Evidence", ""]
        for e in b.evidence:
            alt = e.caption.replace("[", "(").replace("]", ")")
            lines += [f"![{alt}]({image_root}{e.overlay})", "",
                      f"*{e.caption}* ({e.camera_id}, {local_time(e.captured_at, b.utc_offset_hours)})", ""]
    if b.notes:
        lines += ["## Notes", ""] + [f"- {note}" for note in b.notes] + [""]
    lines.append(f"Official source: [{b.official_agency}]({b.official_url})")
    return "\n".join(lines) + "\n"


def _article(b: Bulletin, image_root: str) -> str:
    e = html.escape
    level = LEVELS[b.activity_level]
    parts = ["<article>", f'<p class="disclaimer">{e(b.disclaimer)}</p>', f"<h1>{e(b.headline)}</h1>",
             f"<p>{e(b.volcano_name)} · {e(local_time(b.clock, b.utc_offset_hours))} · Activity: {e(level)}</p>"]
    parts += [f"<p>{e(paragraph.strip())}</p>" for paragraph in b.body.split("\n\n") if paragraph.strip()]
    if b.measurements:
        parts += ["<h2>Measurements</h2>", "<table>",
                  "<tr>" + "".join(f"<th>{e(cell)}</th>" for cell in TABLE_HEADER) + "</tr>"]
        parts += ["<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in table_rows(b)]
        parts.append("</table>")
    if b.wind:
        parts += ["<h2>Wind</h2>", f"<p>{e(wind_text(b))}</p>"]
    if b.evidence:
        parts.append("<h2>Evidence</h2>")
        for item in b.evidence:
            when = local_time(item.captured_at, b.utc_offset_hours)
            parts.append(f'<figure><img src="{e(image_root + item.overlay)}" alt="{e(item.caption)}">'
                         f"<figcaption>{e(item.caption)} ({e(item.camera_id)}, {e(when)})</figcaption></figure>")
    if b.notes:
        parts += ["<h2>Notes</h2>", "<ul>"]
        parts += [f"<li>{e(note)}</li>" for note in b.notes] + ["</ul>"]
    parts += [f'<p>Official source: <a href="{e(b.official_url)}">{e(b.official_agency)}</a></p>', "</article>"]
    return "\n".join(parts)


def to_html(b: Bulletin, *, image_root: str = "") -> str:
    """The bulletin as one HTML page."""
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{html.escape(b.headline)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
            f"{_article(b, image_root)}\n</body>\n</html>\n")


def publish(b: Bulletin, data_dir: Path, out_dir: Path) -> Path:
    """Write bulletin.html and bulletin.md into out_dir/run<run id>, and delete the bilingual pages an older version
    left there; returns that folder."""
    folder = out_dir / f"run{b.run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    root = Path(os.path.relpath(data_dir, folder)).as_posix() + "/"
    (folder / "bulletin.html").write_text(to_html(b, image_root=root), encoding="utf-8")
    (folder / "bulletin.md").write_text(to_markdown(b, image_root=root), encoding="utf-8")
    for name in LEGACY_FILES:
        (folder / name).unlink(missing_ok=True)
    return folder
