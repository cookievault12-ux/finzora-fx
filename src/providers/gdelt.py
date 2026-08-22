"""GDELT 2.0 event client — Phase 3 free geopolitical/news event feed.

Fully free: no API key, direct CSV downloads from data.gdeltproject.org,
updated every 15 minutes (see Phase 3 research — no cost/quota concern).
This client only parses the Events table (not Mentions or the GKG), since
Events already carries what's needed for a first-pass rule-based
geopolitical score: GoldsteinScale (event impact, -10..+10), AvgTone,
NumMentions/NumSources/NumArticles, actor country codes, and CAMEO event
codes.

Column layout is GDELT 2.0's fixed 61-column tab-delimited schema (files
have a ".csv" extension but are NOT comma-delimited — confirmed against
GDELT's own published schema during development). See
http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
for the full 61-column reference if this ever needs extending.

lastupdate.txt (the "what's the latest file" index) was fetched live
during development to confirm the URL format is exactly as documented.
Downloading and parsing a full multi-MB events zip end-to-end was NOT run
in the build sandbox (no outbound network egress there for that size of
transfer, and the parsing logic below was instead verified against a
synthetic row built to GDELT's exact published column layout — see
tests/test_gdelt.py). Smoke-test against one real live file before
relying on this in production.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from dataclasses import dataclass

import httpx

_LAST_UPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# 0-indexed positions in GDELT 2.0's 61-column Events schema. Only the
# columns this project actually uses are named; everything else in the row
# is ignored. See the codebook link in the module docstring for the rest.
COLUMN_INDEX = {
    "GLOBALEVENTID": 0,
    "Actor1Name": 6,
    "Actor1CountryCode": 7,
    "Actor2Name": 16,
    "Actor2CountryCode": 17,
    "EventRootCode": 28,
    "QuadClass": 29,
    "GoldsteinScale": 30,
    "NumMentions": 31,
    "NumSources": 32,
    "NumArticles": 33,
    "AvgTone": 34,
    "ActionGeo_CountryCode": 53,
    "DATEADDED": 59,
    "SOURCEURL": 60,
}
_EXPECTED_COLUMN_COUNT = 61


@dataclass
class GdeltEvent:
    global_event_id: str
    ts: dt.datetime  # from DATEADDED, UTC
    actor1_name: str | None
    actor1_country_code: str | None
    actor2_name: str | None
    actor2_country_code: str | None
    event_root_code: str
    quad_class: int | None
    goldstein_scale: float | None
    num_mentions: int | None
    num_sources: int | None
    num_articles: int | None
    avg_tone: float | None
    action_geo_country_code: str | None
    source_url: str | None


def _blank_to_none(value: str) -> str | None:
    return value if value else None


def _float_or_none(value: str) -> float | None:
    return float(value) if value else None


def _int_or_none(value: str) -> int | None:
    return int(value) if value else None


def parse_event_row(fields: list[str]) -> GdeltEvent | None:
    """Parses one tab-split GDELT events row into a GdeltEvent, or None if
    the row is malformed/truncated (skipped rather than guessed at — a
    partial row is not a trustworthy event record)."""
    if len(fields) < _EXPECTED_COLUMN_COUNT:
        return None
    try:
        ts = dt.datetime.strptime(
            fields[COLUMN_INDEX["DATEADDED"]], "%Y%m%d%H%M%S"
        ).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    try:
        return GdeltEvent(
            global_event_id=fields[COLUMN_INDEX["GLOBALEVENTID"]],
            ts=ts,
            actor1_name=_blank_to_none(fields[COLUMN_INDEX["Actor1Name"]]),
            actor1_country_code=_blank_to_none(fields[COLUMN_INDEX["Actor1CountryCode"]]),
            actor2_name=_blank_to_none(fields[COLUMN_INDEX["Actor2Name"]]),
            actor2_country_code=_blank_to_none(fields[COLUMN_INDEX["Actor2CountryCode"]]),
            event_root_code=fields[COLUMN_INDEX["EventRootCode"]],
            quad_class=_int_or_none(fields[COLUMN_INDEX["QuadClass"]]),
            goldstein_scale=_float_or_none(fields[COLUMN_INDEX["GoldsteinScale"]]),
            num_mentions=_int_or_none(fields[COLUMN_INDEX["NumMentions"]]),
            num_sources=_int_or_none(fields[COLUMN_INDEX["NumSources"]]),
            num_articles=_int_or_none(fields[COLUMN_INDEX["NumArticles"]]),
            avg_tone=_float_or_none(fields[COLUMN_INDEX["AvgTone"]]),
            action_geo_country_code=_blank_to_none(fields[COLUMN_INDEX["ActionGeo_CountryCode"]]),
            source_url=_blank_to_none(fields[COLUMN_INDEX["SOURCEURL"]]),
        )
    except (ValueError, IndexError):
        return None  # a malformed numeric field — skip this row, don't crash the whole file


class GdeltClient:
    name = "gdelt"

    def __init__(self):
        self._client = httpx.Client(timeout=60.0)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GdeltClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get_latest_event_file_url(self) -> str:
        """lastupdate.txt lists 3 lines (events, mentions, gkg) per
        15-minute batch — this project only uses the events file."""
        resp = self._client.get(_LAST_UPDATE_URL)
        resp.raise_for_status()
        for line in resp.text.strip().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
                return parts[2]
        raise LookupError(f"No .export.CSV.zip entry found in {_LAST_UPDATE_URL}")

    def fetch_events(self, url: str | None = None) -> list[GdeltEvent]:
        """Downloads and parses one 15-minute events file. Pass an explicit
        `url` to re-fetch a specific past file; omit it to get whatever is
        currently latest."""
        url = url or self.get_latest_event_file_url()
        resp = self._client.get(url)
        resp.raise_for_status()
        events: list[GdeltEvent] = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(csv_name) as f:
                reader = csv.reader(
                    io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t"
                )
                for row in reader:
                    event = parse_event_row(row)
                    if event is not None:
                        events.append(event)
        return events
