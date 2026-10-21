"""Safe widget metadata for JSON Schemas, including local nullable references."""

from copy import deepcopy


def validate_local_references(root: dict) -> None:
    """Reject dangling/cyclic references even inside nested optional schemas."""
    checked: set[str] = set()

    def walk(value, active=frozenset()):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                if not isinstance(reference, str) or not reference.startswith("#/") or reference in active:
                    raise ValueError("Only acyclic local JSON Schema references are supported")
                if reference not in checked:
                    target = root
                    for token in reference[2:].split("/"):
                        token = token.replace("~1", "/").replace("~0", "~")
                        target = target[int(token)] if isinstance(target, list) else target[token]
                    if not isinstance(target, (dict, bool)):
                        raise ValueError("Schema reference must resolve to a schema")
                    walk(target, active | {reference})
                    checked.add(reference)
            for child in value.values():
                walk(child, active)
        elif isinstance(value, list):
            for child in value:
                walk(child, active)

    walk(root)


def resolve_property(value: dict, root: dict, seen: frozenset[str] = frozenset()) -> dict:
    result = deepcopy(value)
    reference = result.pop("$ref", None)
    if reference is not None:
        if not isinstance(reference, str) or not reference.startswith("#/") or reference in seen:
            raise ValueError("Only acyclic local JSON Schema references are supported")
        target = root
        for token in reference[2:].split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        result = {**resolve_property(target, root, seen | {reference}), **result}
    return result


def parameter_type(value: dict) -> str:
    kind = value.get("type")
    if isinstance(kind, list):
        kinds = [item for item in kind if item != "null"]
        if len(kinds) != 1:
            raise ValueError(f"Unsupported widget type union: {kind}")
        return kinds[0]
    if isinstance(kind, str):
        return kind
    for key in ("anyOf", "oneOf"):
        branches = [item for item in value.get(key, []) if item.get("type") != "null"]
        if len(branches) == 1:
            # Objects behind a local $ref are edited as JSON and validated by
            # the untouched complete schema; no remote schema is ever fetched.
            return parameter_type(branches[0]) if "type" in branches[0] else "object"
    if value.get("enum") and all(isinstance(item, str) for item in value["enum"]):
        return "string"
    raise ValueError(f"No supported widget type in schema: {value}")
