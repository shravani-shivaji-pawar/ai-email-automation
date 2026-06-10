from __future__ import annotations

import io
from typing import Any

import pandas as pd


def parse_excel(file_bytes: bytes) -> list[dict[str, Any]]:
    df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    df = df.fillna("")
    return df.to_dict(orient="records")


def detect_first_name_column(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None

    keys = [str(k) for k in rows[0].keys()]
    candidates = ("first_name", "firstname", "first name", "name")
    lowered = {k.lower(): k for k in keys}

    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def detect_email_column(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None

    keys = [str(k) for k in rows[0].keys()]
    lowered = {k.lower(): k for k in keys}
    candidates = ("email", "e-mail", "mail", "email_address", "email address")

    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    for k in keys:
        if "email" in k.lower():
            return k
    return None


def personalize_message(template: str, row: dict[str, Any], first_name_column: str | None) -> str:
    message = template
    if first_name_column:
        first_name = str(row.get(first_name_column, "")).strip() or "there"
        message = message.replace("{first_name}", first_name)
    else:
        message = message.replace("{first_name}", "there")

    for key, value in row.items():
        placeholder = "{" + str(key) + "}"
        message = message.replace(placeholder, str(value))

    return message
