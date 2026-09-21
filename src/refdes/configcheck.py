"""One validator for every nested block of the two config files.

The top-level settings were validated first: `schema._validate_settings`
rejects an unknown setting by name, with a did-you-mean, and `release_gate:`
extends the same shape one level down. Everything *below* that was read with a
bare `.get()`, so a typo in a nested key was not an error at all -- `site.titel`
quietly left the title at "Design Reference", `standard.preset:` quietly loaded
no preset -- and a wrong-typed block was worse than quiet: `imports: {up: ...}`
raised a raw `AttributeError` out of `load_project`, which `cli.main` only
catches for `SchemaError`, so the user got a traceback.

This module is where both answers live. `BlockChecker.keys` is the one
unknown-key message (block path, the key, the legal keys, a difflib
did-you-mean); `mapping`/`list_of`/`string`/`boolean`/`whole` are the one
wrong-type message, and they replace the coercions that made a wrong type
silently wrong -- a bare string iterated per character (`site.nav`,
`units.preferred`, `include:`), a float `id.width` truncated to an int, a
quoted `"no"` read as true.

Two entry points. `validate_settings` checks the blocks of
`refdes-project.yaml` and returns the resolved values, so `load_project` never
reads a block it has not validated. `validate_overlay` checks the three
namespaces of `refdes-schema.yaml` in the shape `standards.resolve_schema`
consumes them.

Both check *project-authored* input only. The bundled standard and its presets
flow through the same parsing loop but are not checked here, so a bundle
shipped by a newer refdes can still carry a key an older parser ignores.
"""

from __future__ import annotations

import difflib
from typing import Any

from . import theme as theme_mod
from .model import ON_CHANGE_MODES, SchemaError

# What a field's `type:` may be. Derived from the one mapping of declared field
# types (schema_json._FIELD_TYPE_MAP, which `refdes new` and
# `refdes schema --json` both read) plus `enum`, which that map handles
# separately because it needs the field's own choices.
from .schema_json import _FIELD_TYPE_MAP

FIELD_TYPES = frozenset(_FIELD_TYPE_MAP) | {"enum"}

SITE_KEYS = frozenset(
    {"title", "out", "version", "pages", "nav", "assets", "theme", "tokens"}
)
ID_KEYS = frozenset({"width", "ledger"})
HISTORY_KEYS = frozenset({"default"})
COVERAGE_KEYS = frozenset({"group_inherited"})
UNITS_KEYS = frozenset({"preferred", "aliases"})
STANDARD_KEYS = frozenset({"base", "version", "presets"})
BOARD_KEYS = frozenset({"label", "token", "path", "conforms_to", "includes"})
WORKSPACE_KEYS = frozenset({"label", "shared", "path"})
IMPORT_KEYS = frozenset({"name", "items", "version"})
TYPE_KEYS = frozenset(
    {
        "prefix",
        "label",
        "plural",
        "include",
        "extends",
        "fields",
        "links",
        "body",
        "preview",
        "append_only",
        "satisfying_statuses",
        "verifying_statuses",
        "check_severity",
        "coverable",
        "coverable_statuses",
        "doc",
    }
)
FIELD_KEYS = frozenset(
    {"type", "on_change", "required", "required_when", "choices", "default", "doc"}
)
BODY_KEYS = frozenset({"on_change", "required"})

# A set is a fragment of the type's own spec and carries exactly these
# (docs/design/composition.md §1.7); every other key is a loud error.
_SET_ENTRY_KEYS = frozenset({"fields", "links", "body"})
LINK_TYPE_KEYS = frozenset({"inverse", "label", "trace", "doc"})
EQUATION_KEYS = frozenset({"params", "expr", "note"})


def _got(value: Any) -> str:
    """A value as it appears in a diagnostic, shortened when it is a whole mapping."""
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


class BlockChecker:
    """The messages for one config file. `source` is the file named in each."""

    def __init__(self, source: str) -> None:
        self.source = source

    def error(self, message: str) -> SchemaError:
        return SchemaError(f"{self.source}: {message}")

    def wrong(self, path: str, what: str, value: Any) -> SchemaError:
        return self.error(f"{path} must be {what}, got {_got(value)}")

    def keys(self, block: dict, known: frozenset, path: str, what: str) -> None:
        """Reject every key of `block` outside `known`, naming each one's block path.

        All of them at once: a block with two typos is one read of an error,
        not one per `refdes check`.
        """
        unknown = [key for key in block if key not in known]
        if not unknown:
            return
        first, rest = unknown[0], unknown[1:]
        message = (
            f"{path}.{first} is not valid -- {what} takes "
            f"{', '.join(sorted(known))}{self._hint(first, known)}"
        )
        if rest:
            message += " Also unknown: " + "; ".join(
                f"{path}.{key}{self._hint(key, known)}" for key in rest
            )
        raise self.error(message)

    def _hint(self, key: Any, known: frozenset) -> str:
        # 0.6, not difflib's 0.5: at 0.5 `unit` is "close" to `note`, and a
        # wrong suggestion is worse than none -- every real typo this has to
        # catch (`titel`, `labl`, `requird`, `trac`, ...) scores 0.8 or above.
        close = difflib.get_close_matches(str(key), sorted(known), n=1, cutoff=0.6)
        return f". Did you mean {close[0]!r}?" if close else ""

    def mapping(self, value: Any, path: str, what: str) -> dict:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise self.wrong(path, what, value)
        return value

    def list_of(self, value: Any, path: str, what: str) -> list:
        if value is None:
            return []
        if not isinstance(value, list):
            raise self.wrong(path, what, value)
        return list(value)

    def string_list(self, value: Any, path: str, what: str) -> list[str]:
        """A list of strings. A bare string here is the classic per-character
        bug (`nav: index` becoming i, n, d, e, x), so it is refused, not split."""
        items = self.list_of(value, path, what)
        for item in items:
            if not isinstance(item, str):
                raise self.error(
                    f"{path} must be {what}, got the non-string entry {_got(item)}"
                )
        return items

    def string(self, value: Any, path: str, default: str = "") -> str:
        if value is None:
            return default
        if not isinstance(value, str):
            raise self.wrong(path, "a string", value)
        return value

    def boolean(self, value: Any, path: str, default: bool = False) -> bool:
        """A quoted "no" is a string, and a string is truthy: `shared: "no"`
        meant yes. Only true and false are yes and no here."""
        if value is None:
            return default
        if not isinstance(value, bool):
            raise self.wrong(path, "true or false", value)
        return value

    def whole(self, value: Any, path: str, default: int) -> int:
        """`width: 4.5` truncated to 4 silently; `width: four` was a ValueError
        out of int(). Both are a configuration error now."""
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise self.wrong(path, "a whole number", value)
        return value

    def definition(self, value: Any, path: str) -> str:
        """A `doc:` definition (finding 38): prose, or nothing at all.

        Empty is refused rather than rendered -- `doc:` with no text behind it
        is the shape the completeness lint of chunk 2 has to catch, and a
        mapping or a list is a definition that will render as `{'en': 'x'}`.
        """
        if value is None:
            return ""
        if not isinstance(value, str) or not value.strip():
            raise self.wrong(path, "a non-empty string", value)
        return value

    def mode(self, value: Any, path: str, default: str) -> str:
        if value is None:
            return default
        if value not in ON_CHANGE_MODES:
            raise self.wrong(path, f"one of {list(ON_CHANGE_MODES)}", value)
        return str(value)

    # ------------------------------------------------------- settings blocks

    def site(self, raw: dict) -> dict:
        block = self.mapping(raw.get("site"), "site", "a mapping of site settings")
        self.keys(block, SITE_KEYS, "site", "site:")
        theme = self.string(block.get("theme"), "site.theme", theme_mod.DEFAULT_THEME)
        try:
            theme_mod.validate_theme_name(theme)
            tokens = theme_mod.validate_token_overrides(block.get("tokens"))
        except SchemaError as exc:
            # The theme module's own messages, in this file's voice: same text,
            # with the config file named in front of it like every other
            # settings diagnostic.
            raise self.error(str(exc)) from None
        return {
            "theme": theme,
            "tokens": tokens,
            "title": self.string(block.get("title"), "site.title", "Design Reference")
            or "Design Reference",
            "out": self.string(block.get("out"), "site.out", "_site") or "_site",
            "version": self.string(block.get("version"), "site.version"),
            "pages": self.string(block.get("pages"), "site.pages", "pages") or "pages",
            "nav": self.string_list(block.get("nav"), "site.nav", "a list of page slugs"),
            "assets": self.string_list(
                block.get("assets"), "site.assets", "a list of asset directories"
            ),
        }

    def id(self, raw: dict) -> dict:
        block = self.mapping(raw.get("id"), "id", "a mapping of id settings")
        self.keys(block, ID_KEYS, "id", "id:")
        return {
            "width": self.whole(block.get("width"), "id.width", 3),
            "ledger": self.string(
                block.get("ledger"), "id.ledger", ".refdes/ids.yaml"
            )
            or ".refdes/ids.yaml",
        }

    def history(self, raw: dict) -> dict:
        block = self.mapping(raw.get("history"), "history", "a mapping of history settings")
        self.keys(block, HISTORY_KEYS, "history", "history:")
        return {"default": self.mode(block.get("default"), "history.default", "invalidate")}

    def coverage(self, raw: dict) -> dict:
        block = self.mapping(raw.get("coverage"), "coverage", "a mapping of coverage settings")
        self.keys(block, COVERAGE_KEYS, "coverage", "coverage:")
        group = block.get("group_inherited", True)
        if not isinstance(group, bool):
            raise self.wrong("coverage.group_inherited", "true or false", group)
        return {"group_inherited": group}

    def units(self, raw: dict) -> dict:
        block = self.mapping(raw.get("units"), "units", "a mapping of unit settings")
        self.keys(block, UNITS_KEYS, "units", "units:")
        aliases = self.mapping(block.get("aliases"), "units.aliases", "a mapping of alias to unit")
        for alias, target in aliases.items():
            if not isinstance(target, str):
                raise self.error(
                    f"units.aliases must be a mapping of alias to unit, and "
                    f"{alias!r} maps to the non-string {_got(target)}"
                )
        return {
            "preferred": self.string_list(
                block.get("preferred"), "units.preferred", "a list of unit names"
            ),
            "aliases": dict(aliases),
        }

    def standard(self, raw: dict) -> None:
        """Only the keys of a mapping form: `none`, and a value that is neither
        a mapping nor the escape hatch, are `standards.resolve_schema`'s to
        report -- it has the message about what `standard:` may be."""
        block = raw.get("standard")
        if isinstance(block, dict):
            self.keys(block, STANDARD_KEYS, "standard", "standard:")

    def boards(self, raw: dict) -> dict[str, dict]:
        block = self.mapping(raw.get("boards"), "boards", "a mapping of board name to board settings")
        boards: dict[str, dict] = {}
        for name, entry in block.items():
            path = f"boards.{name}"
            spec = self.mapping(entry, path, "a mapping of board settings")
            self.keys(spec, BOARD_KEYS, path, "a boards: entry")
            boards[name] = {
                "label": self.string(spec.get("label"), f"{path}.label", str(name))
                or str(name),
                "token": self.string(spec.get("token"), f"{path}.token"),
                "path": self.string(spec.get("path"), f"{path}.path"),
                "conforms_to": self._conforms_to(spec.get("conforms_to"), name),
                "includes": self._includes(spec.get("includes"), name),
            }
        return boards

    def _conforms_to(self, value: Any, bname: str) -> list[str]:
        """A board's `conforms_to:` as a list of group ids.

        A bare string here would otherwise be iterated character by character,
        so `conforms_to: GRP-001` produced one "does not exist" error per letter
        -- a screenful of them to explain a missing pair of brackets.
        """
        path = f"boards.{bname} conforms_to"
        if value is None:
            return []
        if not isinstance(value, list):
            raise self.error(
                f"{path} must be a list of group ids, got {_got(value)} -- "
                "write conforms_to: [GRP-001]"
            )
        return self.string_list(value, path, "a list of group ids")

    def _includes(self, value: Any, bname: str) -> list[str]:
        """A board's `includes:` as a list of group ids -- validated exactly like
        `conforms_to:` (finding 33): a bare string is a configuration error, not
        a per-character list of one-letter groups."""
        path = f"boards.{bname} includes"
        if value is None:
            return []
        if not isinstance(value, list):
            raise self.error(
                f"{path} must be a list of group ids, got {_got(value)} -- "
                "write includes: [GRP-001]"
            )
        return self.string_list(value, path, "a list of group ids")

    def workspaces(self, raw: dict) -> dict[str, dict]:
        block = self.mapping(
            raw.get("workspaces"), "workspaces", "a mapping of workspace name to workspace settings"
        )
        workspaces: dict[str, dict] = {}
        for name, entry in block.items():
            path = f"workspaces.{name}"
            spec = self.mapping(entry, path, "a mapping of workspace settings")
            self.keys(spec, WORKSPACE_KEYS, path, "a workspaces: entry")
            workspaces[name] = {
                "label": self.string(spec.get("label"), f"{path}.label", str(name))
                or str(name),
                "shared": self.boolean(spec.get("shared"), f"{path}.shared"),
                "path": self.string(spec.get("path"), f"{path}.path"),
            }
        return workspaces

    def imports(self, raw: dict) -> list[dict]:
        entries = self.list_of(raw.get("imports"), "imports", "a list of entries")
        specs: list[dict] = []
        for index, entry in enumerate(entries):
            path = f"imports[{index}]"
            spec = self.mapping(entry, path, "a mapping with 'name' and 'items'")
            self.keys(spec, IMPORT_KEYS, path, "an imports: entry")
            if not spec.get("name") or not spec.get("items"):
                raise self.error(f"{path} needs 'name' and 'items'")
            specs.append(
                {
                    "name": self.string(spec.get("name"), f"{path}.name"),
                    "items": self.string(spec.get("items"), f"{path}.items"),
                    "version": (
                        self.string(spec.get("version"), f"{path}.version")
                        if spec.get("version") is not None
                        else None
                    ),
                }
            )
        return specs

    # -------------------------------------------------------- overlay blocks

    def field_spec(self, spec: Any, path: str) -> dict | None:
        """One field definition, as it appears under a type's `fields:` or a
        set's own mapping. None is a deletion of an inherited field."""
        if spec is None:
            return None
        block = self.mapping(spec, path, "a mapping of settings")
        self.keys(block, FIELD_KEYS, path, "a field spec")
        declared = block.get("type", "text")
        if declared not in FIELD_TYPES:
            raise self.wrong(
                f"{path}.type", f"one of the field types {sorted(FIELD_TYPES)}", declared
            )
        if "choices" in block:
            self.string_list(block.get("choices"), f"{path}.choices", "a list of choices")
        if "required" in block:
            self.boolean(block.get("required"), f"{path}.required")
        if "doc" in block:
            self.definition(block.get("doc"), f"{path}.doc")
        return block

    def field_map(self, value: Any, path: str) -> dict:
        fields = self.mapping(value, path, "a mapping of field name to field spec")
        for fname, fspec in fields.items():
            self.field_spec(fspec, f"{path}.{fname}")
        return fields

    def sets(self, raw: dict) -> None:
        block = self.mapping(
            raw.get("sets"), "sets", "a mapping of set name to its contents"
        )
        for name, entry in block.items():  # the set names themselves are the project's own
            path = f"sets.{name}"
            if entry is None:
                continue
            spec = self.mapping(
                entry, path, "a mapping of set contents: fields, links and body"
            )
            # A set is a type-spec fragment carrying exactly three keys
            # (docs/design/composition.md §1). Anything else -- include,
            # coverable, prefix, or a bare field name from the pre-rename
            # direct form -- is named, not passed through.
            for key in spec:
                if key not in _SET_ENTRY_KEYS:
                    raise self.error(
                        f"{path} may not declare {key!r}: a set carries fields, "
                        "links and body only"
                    )
            if "fields" in spec:
                self.field_map(spec["fields"] or {}, f"{path}.fields")
            if "links" in spec:
                links = self.mapping(
                    spec["links"], f"{path}.links", "a mapping of link name to allowed target types"
                )
                for lname, targets in links.items():
                    self.string_list(
                        targets, f"{path}.links.{lname}", "a list of target type names"
                    )
            if "body" in spec:
                body = self.mapping(spec["body"], f"{path}.body", "a mapping of body settings")
                self.keys(body, BODY_KEYS, f"{path}.body", "a body: block")
                if "on_change" in body:
                    self.mode(body.get("on_change"), f"{path}.body.on_change", "invalidate")

    def link_types(self, raw: dict) -> None:
        block = self.mapping(
            raw.get("link_types"), "link_types", "a mapping of link type name to its settings"
        )
        for name, entry in block.items():
            path = f"link_types.{name}"
            if entry is None:
                continue
            spec = self.mapping(entry, path, "a mapping of link type settings")
            self.keys(spec, LINK_TYPE_KEYS, path, "a link_types: entry")
            self.string(spec.get("inverse"), f"{path}.inverse")
            self.string(spec.get("label"), f"{path}.label")
            self.boolean(spec.get("trace"), f"{path}.trace", True)
            self.definition(spec.get("doc"), f"{path}.doc")

    def types(self, raw: dict) -> None:
        block = self.mapping(raw.get("types"), "types", "a mapping of type name to its settings")
        for name, entry in block.items():
            # `types.<name>: null` removes an inherited type, so None is legal here.
            if entry is None:
                continue
            self.type_entry(entry, f"types.{name}")

    def type_entry(self, entry: Any, path: str) -> None:
        spec = self.mapping(entry, path, "a mapping of type settings")
        self.keys(spec, TYPE_KEYS, path, "a types: entry")
        self.string(spec.get("prefix"), f"{path}.prefix")
        if "extends" in spec:
            self.string(spec.get("extends"), f"{path}.extends")
        self.string(spec.get("label"), f"{path}.label")
        self.string(spec.get("plural"), f"{path}.plural")
        self.definition(spec.get("doc"), f"{path}.doc")
        if "include" in spec:
            self.string_list(spec.get("include"), f"{path}.include", "a list of set names")
        self.field_map(spec.get("fields") or {}, f"{path}.fields")
        links = self.mapping(spec.get("links"), f"{path}.links", "a mapping of link name to allowed target types")
        for lname, targets in links.items():
            self.string_list(targets, f"{path}.links.{lname}", "a list of target type names")
        body = self.mapping(spec.get("body"), f"{path}.body", "a mapping of body settings")
        self.keys(body, BODY_KEYS, f"{path}.body", "a body: block")
        if "on_change" in body:
            self.mode(body.get("on_change"), f"{path}.body.on_change", "invalidate")
        self.boolean(spec.get("append_only"), f"{path}.append_only")
        if spec.get("coverable") is not None:
            self.boolean(spec.get("coverable"), f"{path}.coverable")
        self.string_list(spec.get("preview"), f"{path}.preview", "a list of field names")
        for key in ("satisfying_statuses", "verifying_statuses", "coverable_statuses"):
            if spec.get(key) is not None:
                self.string_list(spec.get(key), f"{path}.{key}", "a list of status values")


def validate_settings(raw: dict[str, Any], source: str) -> dict[str, Any]:
    """Validate every nested block of the project settings file.

    Returns the resolved values -- defaults filled, types checked -- so
    `load_project` builds its objects from these and never re-reads a block
    unvalidated. `standard:` is checked for keys only and resolved by
    `standards.resolve_schema`, which owns what it may be.
    """
    check = BlockChecker(source)
    check.standard(raw)
    return {
        "site": check.site(raw),
        "id": check.id(raw),
        "history": check.history(raw),
        "coverage": check.coverage(raw),
        "units": check.units(raw),
        "boards": check.boards(raw),
        "workspaces": check.workspaces(raw),
        "imports": check.imports(raw),
    }


def validate_overlay(raw: dict[str, Any], source: str) -> None:
    """Validate the project's own `types:`/`link_types:`/`sets:`.

    Structure only: the merged result still goes through `load_project`'s
    parsing loop, which owns the cross-checks (an unknown link name, a
    `required_when:` pointing at a field that is not there).
    """
    check = BlockChecker(source)
    check.sets(raw)
    check.link_types(raw)
    check.types(raw)
