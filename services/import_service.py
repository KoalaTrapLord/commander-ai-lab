"""Collection import service: CSV/text parsing helpers."""
import csv
import io
import re
from typing import Optional


def _parse_finish(raw: str) -> str:
    if not raw:
        return "NORMAL"
    r = raw.strip().lower()
    if r in ("etched", "foil etched", "foil_etched", "etched foil"):
        return "ETCHED"
    if r in ("yes", "foil", "true", "1"):
        return "FOIL"
    return "NORMAL"


def _parse_text_line(line: str) -> dict:
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return {}
    result = {"name": "", "quantity": 1, "set_code": "", "collector_number": ""}
    qty_match = re.match(r"^(\d+)x?\s+", line)
    if qty_match:
        result["quantity"] = int(qty_match.group(1))
        line = line[qty_match.end():]
    bracket_match = re.search(r"\[([A-Za-z0-9]+):(\S+)\]\s*$", line)
    if bracket_match:
        result["set_code"] = bracket_match.group(1).lower()
        result["collector_number"] = bracket_match.group(2)
        result["name"] = line[:bracket_match.start()].strip()
        return result
    paren_coll_match = re.search(r"\(([A-Za-z0-9]+)\)\s+(\S+)\s*$", line)
    if paren_coll_match:
        result["set_code"] = paren_coll_match.group(1).lower()
        result["collector_number"] = paren_coll_match.group(2)
        result["name"] = line[:paren_coll_match.start()].strip()
        return result
    paren_match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", line)
    if paren_match:
        result["set_code"] = paren_match.group(1).lower()
        result["name"] = line[:paren_match.start()].strip()
        return result
    result["name"] = line.strip()
    return result


def _auto_infer_mapping(headers: list) -> dict:
    mapping = {}
    header_lower = {h: h.lower().strip() for h in headers}
    field_patterns = {
        "name": ["name", "card name", "card_name", "cardname", "title"],
        "quantity": ["quantity", "qty", "count", "amount", "number", "#"],
        "set_code": ["set", "set code", "set_code", "edition", "set_name", "edition code"],
        "collector_number": ["collector number", "collector_number", "collectornumber", "col #", "col#", "number", "card number"],
        "finish": ["finish", "foil", "printing", "treatment"],
        "condition": ["condition", "cond", "grade"],
        "language": ["language", "lang", "locale"],
        "notes": ["notes", "note", "comments", "comment"],
        "tags": ["tags", "tag", "labels", "label"],
    }
    for header, lower_h in header_lower.items():
        for field, patterns in field_patterns.items():
            if lower_h in patterns:
                mapping[header] = field
                break
    return mapping


def _parse_csv_content(content: str, source: str, mapping: Optional[dict]) -> list:
    rows = []
    if (source or "").upper() == "TEXT":
        for line in content.splitlines():
            parsed = _parse_text_line(line)
            if parsed.get("name"):
                rows.append(parsed)
        return rows
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    col_map = {h: (mapping.get(h, "") if mapping else "") for h in headers}
    if not mapping:
        col_map = _auto_infer_mapping(headers)
    col_map = {h: (v.lower() if isinstance(v, str) else v) for h, v in col_map.items()}
    for csv_row in reader:
        row = {"name": "", "quantity": 1, "set_code": "", "collector_number": "",
               "finish": "NORMAL", "condition": "", "language": "", "notes": "", "tags": ""}
        for header, field in col_map.items():
            val = csv_row.get(header, "").strip()
            if not val or field == "ignore" or not field:
                continue
            if field == "name":
                val = re.sub(r"\s*\(foil(?: etched)?\)\s*$", "", val, flags=re.IGNORECASE).strip()
                row["name"] = val
            elif field == "quantity":
                try:
                    row["quantity"] = int(float(val))
                except ValueError:
                    row["quantity"] = 1
            elif field in ("set_code", "set_code_secondary"):
                row["set_code"] = val.lower()
            elif field in ("collector_number", "collector_number_secondary"):
                row["collector_number"] = val
            elif field == "finish":
                row["finish"] = _parse_finish(val)
            elif field in ("condition", "language", "notes", "tags"):
                row[field] = val
        if row["name"]:
            rows.append(row)
    return rows
