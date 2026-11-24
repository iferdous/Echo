"""Create an offline, read-only review of Echo's batch audit artifacts."""

import hashlib
import io
import json
from collections import Counter, defaultdict
from html import escape
from importlib.resources import files
from pathlib import Path
from string import Template

from echo.artifacts import new_output_file
from echo.batch import CANDIDATE_COLUMNS, QUERY_COLUMNS
from echo.datasets import csv_rows

STATES = {
    "matched": (
        "Accepted",
        "Listen at the reported intervals and review provenance before changing either split.",
    ),
    "no_match": (
        "No accepted match",
        "Review strong candidates and verify the index covers the recordings you expected.",
    ),
    "insufficient_evidence": (
        "Insufficient evidence",
        "Try a longer excerpt with the sound event present and run the query again.",
    ),
    "input_error": (
        "Input error",
        "Check the file and its checksum or path, then rerun with a fresh output folder.",
    ),
}


def read_verified_rows(
    path: Path, columns: tuple, expected: str
) -> list[dict[str, str]]:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(
            f"{path.name} does not match audit.json; use files from one audit run"
        )
    with io.StringIO(data.decode("utf-8-sig"), newline="") as content:
        return list(csv_rows(content, columns, name=path.name))


def read_evidence(root: Path) -> tuple[dict, list[dict], dict[str, list[dict]]]:
    record = json.loads((root / "audit.json").read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("review requires an Echo batch audit with schema version 1")
    queries = read_verified_rows(
        root / "queries.csv", QUERY_COLUMNS, record["queries_sha256"]
    )
    ranks = read_verified_rows(
        root / "candidates.csv", CANDIDATE_COLUMNS, record["candidates_sha256"]
    )
    query_ids = {row["query_id"] for row in queries}
    counts = Counter(row["decision"] for row in queries)
    if (
        len(queries) != record["query_count"]
        or len(query_ids) != len(queries)
        or len(ranks) != record["candidate_count"]
        or counts != record["decisions"]
        or counts.keys() - STATES.keys()
        or any(row["run_id"] != record["run_id"] for row in (*queries, *ranks))
    ):
        raise ValueError("audit row identities or totals do not agree with audit.json")
    candidates = defaultdict(list)
    for row in ranks:
        if row["query_id"] not in query_ids:
            raise ValueError("candidate row has no query in this run")
        candidates[row["query_id"]].append(row)
    for row in queries:
        ranked = candidates[row["query_id"]]
        accepted = row["decision"] == "matched"
        if (
            [int(candidate["rank"]) for candidate in ranked]
            != list(range(1, len(ranked) + 1))
            or [candidate["accepted"] for candidate in ranked]
            != [str(accepted and index == 0) for index in range(len(ranked))]
            or (
                ranked
                and (ranked[0]["reference_id"], ranked[0]["offset_seconds"])
                != (row["best_reference"], row["offset_seconds"])
            )
            or (
                not ranked
                and (accepted or row["best_reference"] or row["offset_seconds"])
            )
            or (row["decision"] in {"input_error", "insufficient_evidence"} and ranked)
        ):
            raise ValueError(
                f"{row['query_id']}: candidate ranking or acceptance is inconsistent"
            )
    return record, queries, candidates


def label_offset(value: str) -> str:
    return f"{float(value):+.3f} s" if value else "—"


def candidate_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="quiet">No ranked candidates.</p>'
    cells = []
    for item in rows:
        q_span = f"{float(item['query_start_seconds']):.3f}–{float(item['query_end_seconds']):.3f} s"
        r_span = f"{float(item['reference_start_seconds']):.3f}–{float(item['reference_end_seconds']):.3f} s"
        decision = "Accepted" if item["accepted"] == "True" else "Ranked only"
        cells.append(
            f"<tr><td>{int(item['rank'])}</td><td><code>{escape(item['reference_id'])}</code>"
            f"<small>{decision}</small></td><td>{label_offset(item['offset_seconds'])}</td>"
            f"<td>{q_span}<small>Reference {r_span}</small></td><td>{int(item['score'])}"
            f"<small>{int(item['anchor_frames'])} anchors</small></td>"
            f"<td>{float(item['coverage']):.1%}<small>{float(item['support_fraction']):.1%} support</small></td></tr>"
        )
    return (
        '<div class="table-scroll" tabindex="0" aria-label="Ranked candidates"><table>'
        "<thead><tr><th scope='col'>Rank</th><th scope='col'>Reference</th>"
        "<th scope='col'>Offset</th><th scope='col'>Query interval</th>"
        "<th scope='col'>Votes</th><th scope='col'>Coverage</th></tr></thead>"
        f"<tbody>{''.join(cells)}</tbody></table></div>"
    )


def query_item(row: dict, candidates: list[dict]) -> str:
    status = row["decision"]
    title, action = STATES[status]
    names = " ".join([row["query_id"], *(c["reference_id"] for c in candidates)])
    error = f'<p class="problem">{escape(row["message"])}</p>' if row["message"] else ""
    landmark_count = escape(row["query_landmarks"]) or "—"
    return f"""
    <details class="query" data-state="{status}" data-names="{escape(names, quote=True)}">
      <summary>
        <span class="query-id"><code>{escape(row["query_id"])}</code></span>
        <span class="status {status}">{title}</span>
        <span class="reference"><code>{escape(row["best_reference"]) or "—"}</code></span>
        <span class="offset">{label_offset(row["offset_seconds"])}</span>
      </summary>
      <div class="inside"><p>{action}</p>{error}
        <p class="quiet">Query landmarks <strong>{landmark_count}</strong></p>
        {candidate_table(candidates)}
      </div>
    </details>"""


def render_review(root: Path, destination: Path) -> int:
    record, queries, candidates = read_evidence(root)
    template = Template(
        files("echo").joinpath("review.html").read_text(encoding="utf-8")
    )
    counts = "".join(
        f"<div><dt>{title}</dt><dd>{record['decisions'].get(state, 0):,}</dd></div>"
        for state, (title, _) in STATES.items()
    )
    if not queries:
        items = '<p class="empty">This audit contains no query rows.</p>'
    else:
        items = "".join(query_item(row, candidates[row["query_id"]]) for row in queries)
    page = template.substitute(
        counts=counts,
        run_id=escape(record["run_id"]),
        reference_count=f"{int(record['indexed_assets']):,}",
        query_count=f"{len(queries):,}",
        candidate_count=f"{int(record['candidate_count']):,}",
        policy_sha256=escape(record["match_policy_sha256"]),
        items=items,
    )
    with new_output_file(destination) as temporary:
        temporary.write_text(page, encoding="utf-8")
    return len(queries)
