"""Lifting the username and the URL out of an entry's text, and putting them back.

An entry is free text below its password, and the pane picks two of its lines
out by name. The editor offers those two as rows of their own, which means
taking them out of the text on the way in and writing them back on the way out
-- in the place they had, spelled the way they were, so a store written by
another tool stays readable by that tool and nothing else in the entry moves.
"""

from dataclasses import dataclass

from gtkpass.backends import metadata_pair


@dataclass
class LiftedField:
    """One line taken out of the details, and everything needed to put it back."""

    #: Where the line sat among the details, so it goes back there.
    index: int
    #: The line exactly as written, reused untouched when the value has not
    #: changed: odd spacing is not ours to tidy.
    line: str
    #: The key as written, ``User`` or ``login``, kept for a rewritten line.
    key: str
    #: The value as the pane would read it.
    value: str


@dataclass
class LiftedDetails:
    """The details with the two known fields taken out."""

    text: str
    username: LiftedField | None
    url: LiftedField | None


def lift(details: str, username_keys: tuple[str, ...], url_keys: tuple[str, ...]):
    """Take the first username line and the first URL line out of ``details``.

    Only the first of each: a second spelling of the same field is left where
    it is, because there is only one row to show it in and quietly dropping
    it would lose what the store carried.
    """
    lines = details.split("\n")
    username: LiftedField | None = None
    url: LiftedField | None = None
    kept: list[str] = []
    for line in lines:
        pair = metadata_pair(line)
        if pair is not None:
            key, value = pair
            written_key = line.partition(":")[0].strip()
            if username is None and key in username_keys:
                username = LiftedField(len(kept), line, written_key, value)
                continue
            if url is None and key in url_keys:
                url = LiftedField(len(kept), line, written_key, value)
                continue
        kept.append(line)
    return LiftedDetails("\n".join(kept), username, url)


def lower(
    details: str,
    username: str,
    url: str,
    lifted_username: LiftedField | None,
    lifted_url: LiftedField | None,
) -> str:
    """Put the two fields back into ``details``.

    A field that was lifted goes back where it was, as the same line when its
    value is unchanged and as ``key: value`` with its original key otherwise;
    an emptied one is dropped. A field the entry never had goes in first,
    under the key the pane reads by default, the username before the URL.
    """
    lines = details.split("\n")
    for lifted, value, default_key in sorted(
        ((lifted_url, url, "url"), (lifted_username, username, "username")),
        key=lambda item: item[0].index if item[0] is not None else -1,
        reverse=True,
    ):
        value = value.strip()
        if lifted is None:
            if value:
                lines.insert(0, f"{default_key}: {value}")
            continue
        if not value:
            continue
        line = lifted.line if value == lifted.value else f"{lifted.key}: {value}"
        lines.insert(min(lifted.index, len(lines)), line)
    return "\n".join(lines)
