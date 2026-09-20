"""Status/link agreement warnings -- vocabulary review P11.

`superseded` and `selected` are facts stored twice: once as a status, once as
a link (`supersedes` / `selects`) pointing the other way. The verbs' own
definitions have to disclaim any automatic effect precisely because the state
has two representations that can disagree -- `supersedes:`'s doc says "moving
its status to superseded is your edit, not something the link does by itself",
and `selects:`'s says the component's own status marks it selected. Nothing in
the engine ever checked whether the two halves were telling the same story, so
a decision could `supersedes: [DEC-002]` while DEC-001 and DEC-002 both sat at
`accepted`, and a component could be `selected` with no decision anywhere
claiming to have selected it.

This module reports both halves of that disagreement as **warnings**. It does
not compute one from the other, and it must not: the review's alternative --
derive "superseded" from `supersedes` and drop the status from the enum -- is
a design change this repo has not made, and silently rewriting a status from a
link would make an authored lifecycle field mean whatever the graph happens to
say. `selected` is also component's `satisfying_statuses` value, so coverage
reads it; a warning leaves the author in charge of which half was the mistake.

Two directions per pair, because each half can be the wrong one:

* **link without status** -- `DEC-001 supersedes DEC-002` while DEC-002's
  status is anything but `superseded`. The link was authored; the status was
  not updated (or the link is not true).
* **status without link** -- `CMP-001` is `selected` and no item anywhere
  declares `selects:` pointing at it. The status was set; the decision that
  justifies it was never recorded (or the status is not true).

The pairs are a table, not a derivation: `supersedes`/`superseded` and
`selects`/`selected` are the two the bundled standard stores twice, and
guessing at future ones from word shapes (`verifies`/`verified`?) would warn
about vocabulary that has no status behind it. Each check is guarded on the
vocabulary actually carrying both halves -- the verb must exist in the
project's `link_types`, and the item's own type must declare a `status` field
whose `choices` include the paired value -- so a project that has neither, or
a bespoke schema that borrows the verb name for something else, hears nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Item, Project


@dataclass(frozen=True)
class StatusLinkPair:
    """One fact stored as both a link and a status. `verb` is authored on the
    item that *makes* it so; `status` is the value the link's target is
    expected to carry."""

    verb: str
    status: str


STATUS_LINK_PAIRS: tuple[StatusLinkPair, ...] = (
    StatusLinkPair("supersedes", "superseded"),
    StatusLinkPair("selects", "selected"),
)


def _declares_status(item: Item, project: Project, status: str) -> bool:
    """True when this item's own type declares a `status` enum offering
    `status`. A type with no status field, or one whose choices never include
    the value, can never be in disagreement about it -- the same
    "unconfigured means nothing happens" default coverage uses for
    `satisfying_statuses`."""
    spec = project.types.get(item.type)
    field = spec.fields.get("status") if spec else None
    return bool(getattr(field, "choices", None)) and status in field.choices


def _warn_link_without_status(
    project: Project, pair: StatusLinkPair
) -> None:
    for item in project.local_items:
        stale: list[Item] = []
        for ref in item.resolved_links.get(pair.verb, []):
            target = project.item_by_ref(ref)
            # Imports are read-only here, and an unresolvable ref was already
            # reported by resolve_links().
            if target is None or target.external:
                continue
            if _declares_status(target, project, pair.status) and (
                target.fields.get("status") != pair.status
            ):
                stale.append(target)
        if not stale:
            continue
        if len(stale) == 1:
            target = stale[0]
            project.warn(
                f"{pair.verb} {target.id or target.key}, but that item's status "
                f"is {target.fields.get('status')!r}, not {pair.status!r} -- the "
                f"link does not move a status on its own. Set "
                f"{target.id or target.key}'s status to {pair.status!r}, or "
                f"remove the {pair.verb} link if it is not true.",
                file=item.source_file,
                line=item.source_line,
                item_id=item.id,
            )
        else:
            listed = ", ".join(
                f"{t.id or t.key} ({t.fields.get('status')!r})" for t in stale
            )
            project.warn(
                f"{pair.verb} {len(stale)} items whose status is not "
                f"{pair.status!r}: {listed} -- the link does not move a status "
                f"on its own. Set each one's status to {pair.status!r}, or "
                f"remove the {pair.verb} link from this item if it is not true.",
                file=item.source_file,
                line=item.source_line,
                item_id=item.id,
            )


def _warn_status_without_link(
    project: Project, pair: StatusLinkPair, inverse: str
) -> None:
    for item in project.local_items:
        if item.fields.get("status") != pair.status:
            continue
        if not _declares_status(item, project, pair.status):
            continue
        if item.backlinks.get(inverse):
            continue
        project.warn(
            f"status is {pair.status!r} but nothing {pair.verb} it -- no item "
            f"declares {pair.verb}: pointing at this one. Author {pair.verb}: "
            f"on the item that makes it so, or move this item off "
            f"{pair.status!r}.",
            file=item.source_file,
            line=item.source_line,
            item_id=item.id,
        )


def warn_conflicts(project: Project) -> None:
    """Report every status/link disagreement in the project as a warning.
    Must run after `resolve_links` -- it reads `resolved_links` and
    `backlinks`, and never raw `links`, which can carry `DISPLAY@key` text."""
    for pair in STATUS_LINK_PAIRS:
        link_type = project.link_types.get(pair.verb)
        if link_type is None:
            continue
        _warn_link_without_status(project, pair)
        _warn_status_without_link(project, pair, link_type.inverse)
