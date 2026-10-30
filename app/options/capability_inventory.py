"""Metadata-only inventory. Advertised tools are never automatically authorized."""
import hashlib
import json
import re

MAX_INVENTORY_BYTES = 512 * 1024
MAX_METADATA_BYTES = 384 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def output_paths(schema):
    paths, complete = set(), True
    pending = [(schema, "", 0)]
    visits = 0
    while pending:
        value, prefix, depth = pending.pop()
        visits += 1
        if visits > 4096 or len(paths) >= 256:
            complete = False
            break
        if not isinstance(value, dict):
            continue
        if depth > 12 or "$ref" in value or "$dynamicRef" in value:
            complete = False
            continue
        properties = value.get("properties")
        if isinstance(properties, dict):
            for key, child in properties.items():
                path = prefix + "." + key if prefix else key
                if len(path) > 256:
                    complete = False
                    continue
                paths.add(path)
                pending.append((child, path, depth + 1))
        if isinstance(value.get("items"), dict):
            pending.append((value["items"], prefix + "[]", depth + 1))
        for key in ("anyOf", "oneOf", "allOf"):
            for child in value.get(key, []) if isinstance(value.get(key), list) else []:
                pending.append((child, prefix, depth + 1))
    return sorted(paths), complete


def build(raw, admitted):
    from app.robinhood.gateway import _normalize_tool_metadata

    if not isinstance(raw, list) or len(raw) > 256:
        raise ValueError("Bounded complete tool inventory required")
    tools, names, retained = [], set(), 0
    for item in sorted(raw, key=lambda t: t.get("name", "") if isinstance(t, dict) else ""):
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item["name"])
                or item["name"] in names):
            raise ValueError("Unique bounded tool names required")
        names.add(item["name"])
        metadata = _normalize_tool_metadata(item)
        wire = encoded(metadata)
        annotations = metadata.get("annotations") or {}
        hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
        input_schema, output_schema = metadata.get("inputSchema"), metadata.get("outputSchema")
        properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
        paths, complete = output_paths(output_schema)
        entry = {
            "name": item["name"], "read_only_hint": hint if type(hint) is bool else None,
            "in_runtime_allowlist": item["name"] in admitted,
            "input_fields": sorted(properties)[:128] if isinstance(properties, dict) else [],
            "output_fields": paths, "output_fields_complete": complete and isinstance(output_schema, dict),
            "metadata_sha256": hashlib.sha256(wire).hexdigest(),
            "schemas_retained": False,
        }
        if len(wire) <= 64 * 1024 and retained + len(wire) <= MAX_METADATA_BYTES:
            entry["metadata"] = metadata
            entry["schemas_retained"] = True
            retained += len(wire)
        tools.append(entry)
    result = {"version": "robinhood-capability-inventory-v1", "tools": tools,
              "tool_count": len(tools), "market_tool_calls": 0,
              "execution_authority": False, "live_enabled": False}
    if len(encoded(result)) > MAX_INVENTORY_BYTES:
        raise ValueError("Inventory exceeds evidence bound")
    return result


def summary(inventory):
    """Candidate names/fields are leads for review, never evidence of data coverage."""
    tools = inventory["tools"]
    groups = {
        "stock_quotes_and_sizes": r"equity.*quote|equity.*price_book|stock.*quote|bid_size|ask_size",
        "stock_reference": r"equity.*instrument|equity.*tradab|stock.*instrument|corporate",
        "swing_history": r"equity.*histor|stock.*histor",
        "news_events_and_catalysts": r"news|earning|catalyst|calendar|economic|event",
        "scope_index_and_context": r"index|indices|spx|dealer|gamma_exposure|option.*flow|volatility",
    }
    return {
        "version": inventory["version"], "tool_count": len(tools),
        "tool_index": [{"name": t["name"], "read_only_hint": t["read_only_hint"],
                        "in_runtime_allowlist": t["in_runtime_allowlist"]} for t in tools],
        "candidate_capabilities": {group: [{
            "name": t["name"], "read_only_hint": t["read_only_hint"],
            "input_fields": t["input_fields"], "output_fields": t["output_fields"],
            "output_fields_complete": t["output_fields_complete"],
            "schemas_retained": t["schemas_retained"],
        } for t in tools if re.search(pattern, t["name"] + " " + " ".join(t["output_fields"]), re.I)]
            for group, pattern in groups.items()},
        "interpretation": "SCHEMA_CANDIDATES_ONLY_NOT_VERIFIED_DATA_COVERAGE",
        "market_tool_calls": 0, "additional_tools_enabled": False,
        "execution_authority": False, "live_enabled": False,
    }
