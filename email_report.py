r"""
email_report.py  —  Diesel Exports Weekly Email Report
======================================================

Generates an HTML email with current-month Diesel export analytics for three
regions (same charts/KPIs as export_pace Dash app):

  1. Mideast Gulf
  2. East Coast UAE + Oman + West Coast Saudi Arabia
  3. Russia

Usage
-----
  # Save HTML to scratch/ without sending:
  .venv\Scripts\python.exe email_report.py --save-only

  # Full run (save + send via Kafka):
  .venv\Scripts\python.exe email_report.py

Windows Task Scheduler
  Program : C:\...\Coding\.venv\Scripts\python.exe
  Arguments: C:\...\products_exports_tracking\email_report.py
  Trigger  : Weekly, Monday, 09:30
"""
from __future__ import annotations

import argparse
import calendar
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime

# Resolve project root so export_pace is importable when run from any cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from export_pace.data import get_data_service
from export_pace.figure import (
    FigureOptions,
    make_daily_figure,
    make_destination_figure,
    make_figure,
)
from export_pace.locations import LocationSelection
from export_pace.report_html import fig_to_img_tag, make_kpi_table_html, status_line_text

try:
    from sender import send_email

    _SENDER_AVAILABLE = True
except ImportError:
    _SENDER_AVAILABLE = False


# =============================================================================
# CONFIG
# =============================================================================

@dataclass(frozen=True)
class ReportSection:
    title: str
    zones: tuple[str, ...]


REPORT_SECTIONS: tuple[ReportSection, ...] = (
    ReportSection("Mideast Gulf", ("Mideast Gulf",)),
    ReportSection(
        "East Coast UAE + Oman + West Coast Saudi Arabia",
        ("East Coast UAE", "Oman", "West Coast Saudi Arabia"),
    ),
    ReportSection("Russia", ("Russia",)),
)

PRODUCT = ["Diesel"]
N_HISTORY = 5
FLOW_DIRECTION = "export"
WITH_INTRA_COUNTRY = False
WITH_INTRA_REGION = False

FIG_OPTS = FigureOptions(
    show_bands=True,
    show_median=True,
    show_last_month=True,
    show_last_year=True,
    show_anomalies=True,
)

RECIPIENTS = (
    "luiscarlos.gaitan@jainglobal.com, "
    "yves.Mindren@jainglobal.com, "
    "abderrahmane.mahoudi@jainglobal.com"
)
RECIPIENTS_CC: str | None = None
FROM_ADDRESS = "oil.research.desk@jainglobal.com"

SAVE_COPY = True
SAVE_DIR = os.path.join(_HERE, "scratch")


_EMAIL_CSS = """
<style>
* { box-sizing: border-box; }
body {
  font-family: Calibri, Arial, sans-serif;
  margin: 0; padding: 20px;
  background: #ffffff; color: #1a1a2e;
  font-size: 13px; max-width: 940px;
}
h1  { font-size: 17px; margin: 0 0 2px 0; color: #1a1a2e; }
h2  { font-size: 12px; color: #555; font-weight: normal; margin: 0 0 20px 0; }
h3  { font-size: 13px; color: #1a1a2e; margin: 24px 0 8px 0;
       border-bottom: 1px solid #ddd; padding-bottom: 4px; }
.section  { margin-bottom: 28px; }
.chart    { background: white; margin-bottom: 4px; }
.footnote { font-size: 10px; color: #888; margin-top: 4px; }
.status   { font-size: 11px; color: #666; margin-bottom: 8px; }
.divider  { border: none; border-top: 1px solid #e0e0e0; margin: 20px 0; }
.kpi-table { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 12px; }
.kpi-table th, .kpi-table td { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; }
.kpi-table th { background: #f5f5f5; }
.kpi-sub { color: #888; font-size: 11px; }
</style>
"""


def _silence_loggers() -> None:
    for name in ("plotly", "kaleido", "choreographer", "urllib3", "httpx", "confluent_kafka"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _build_section_html(section: ReportSection, *, today: date) -> tuple[str, date | None]:
    """Fetch data and render one report section."""
    service = get_data_service()
    locations = LocationSelection(zones=section.zones, installations=())
    view = service.build_view(
        locations=locations,
        products=PRODUCT,
        month=today.month,
        target_year=today.year,
        n_history=N_HISTORY,
        as_of_day=None,
        with_forecast_live=False,
        flow_direction=FLOW_DIRECTION,
        with_intra_country=WITH_INTRA_COUNTRY,
        with_intra_region=WITH_INTRA_REGION,
    )

    print(f"  Building charts: {section.title}…", flush=True)

    mtd_fig = make_figure(view, FIG_OPTS)
    daily_fig = make_daily_figure(view, FIG_OPTS)
    dest_fig = make_destination_figure(view)

    mtd_img = fig_to_img_tag(mtd_fig, width=860, height=480)
    daily_img = fig_to_img_tag(daily_fig, width=860, height=280)
    dest_height = max(220, 40 + 28 * min(10, len(view.destinations_mtd.head(10))))
    dest_block = ""
    if dest_fig is not None:
        dest_img = fig_to_img_tag(dest_fig, width=860, height=dest_height)
        dest_block = f"""
  <h3>Top destinations</h3>
  <div class="chart">{dest_img}</div>"""

    warning = ""
    if view.warning:
        warning = f'<p class="footnote" style="color:#b45309;">{view.warning}</p>'

    month_name = calendar.month_name[today.month]
    html = f"""
<div class="section">
  <h3>{section.title}</h3>
  <p class="status">{status_line_text(view)}</p>
  {warning}
  {make_kpi_table_html(view)}
  <div class="chart">{mtd_img}</div>
  <p class="footnote">Cumulative MTD pace — {month_name} {today.year}. Shaded bands: {N_HISTORY}-year range.</p>
  <div class="chart">{daily_img}</div>
  <p class="footnote">Daily exports; orange bars flag volume anomalies (&gt;2σ vs history).</p>
  {dest_block}
</div>
"""
    return html, view.latest_data_day


def generate_html(today: date) -> tuple[str, str]:
    """Build full HTML body and subject line."""
    dt_str = today.strftime("%d %B %Y")
    month_name = calendar.month_name[today.month]

    sections_html: list[str] = []
    latest_dates: list[date] = []
    for section in REPORT_SECTIONS:
        block, latest = _build_section_html(section, today=today)
        sections_html.append(block)
        if latest is not None:
            latest_dates.append(latest)

    db_latest = max(latest_dates).strftime("%d %b %Y") if latest_dates else "n/a"
    subject = (
        f"Diesel Exports Weekly | {today.strftime('%d %b %Y')} | "
        f"{month_name} {today.year} MTD"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Diesel Exports Weekly — {dt_str}</title>
{_EMAIL_CSS}
</head>
<body>

<h1>DIESEL EXPORTS WEEKLY</h1>
<h2>
  Jain Global Research Desk &nbsp;|&nbsp; {dt_str}
  &nbsp;|&nbsp; data as of {db_latest}
  &nbsp;|&nbsp; {month_name} {today.year} MTD
</h2>

<hr class="divider">

{"".join(sections_html)}

<hr class="divider">
<p class="footnote">
  Generated by <em>email_report.py</em> on {datetime.now().strftime('%Y-%m-%d %H:%M')}.
  Source: Kpler Flows. Realized flows may lag 1&ndash;2 days.
</p>

</body>
</html>"""
    return html, subject


def main(save_only: bool = False) -> None:
    _silence_loggers()
    today = date.today()
    print(f"Diesel Exports Weekly Report — {today}", flush=True)

    html_body, subject = generate_html(today)

    saved_path = ""
    if SAVE_COPY or save_only:
        os.makedirs(SAVE_DIR, exist_ok=True)
        fname = f"diesel_exports_weekly_{today.strftime('%Y%m%d')}.html"
        saved_path = os.path.join(SAVE_DIR, fname)
        with open(saved_path, "w", encoding="utf-8") as fh:
            fh.write(html_body)
        print(f"Saved: {saved_path}", flush=True)

    if save_only:
        print("--save-only: skipping email send.", flush=True)
        return

    if not _SENDER_AVAILABLE:
        print(
            "ERROR: sender.py not found next to email_report.py. Cannot send email.",
            flush=True,
        )
        sys.exit(1)

    print(f"Sending to: {RECIPIENTS}", flush=True)
    ok, detail = send_email(
        recipients=RECIPIENTS,
        subject=subject,
        body=html_body,
        from_address=FROM_ADDRESS,
        recipients_cc=RECIPIENTS_CC,
    )
    status = "OK" if ok else "FAIL"
    print(f"Send {status}  [{detail}]", flush=True)
    if not ok:
        sys.exit(1)

    print("Done.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diesel Exports Weekly Email Report")
    parser.add_argument(
        "--save-only",
        action="store_true",
        help="Build and save HTML to scratch/ without sending the email.",
    )
    args = parser.parse_args()
    main(save_only=args.save_only)
