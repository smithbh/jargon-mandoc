#!/usr/bin/env python3
"""
jargon-mandoc.py -- generate a man page from the GNU Info build of the Jargon File.

The input is the Jargon File as distributed in Texinfo `.info` form (e.g.
`jarg400.info`). That format stores the document as a flat list of *nodes*
separated by the field-separator byte 0x1f; each node opens with a
`File:/Node:/Next:/Prev:/Up:` header line. Lexicon entries are the nodes whose
`Up:` field is a letter bucket (`= A =`, `= B =`, ...) and whose body begins
with a `:term:` marker.

This script reconstructs the document in reading order and emits a single
classic `man(7)`-macro page. The lexicon text is rendered verbatim (no-fill):
the Jargon File is hand-wrapped at ~70 columns and contains ASCII art, aligned
tables, and quoted code whose layout reflowing would destroy. Headword terms
are set in bold and `{cross-references}` in italic.

Usage
-----
    python3 jargon-mandoc.py jarg400.info
    python3 jargon-mandoc.py jarg400.info -o ./build --gzip
    python3 jargon-mandoc.py jarg400.info --install            # ~/.local/share/man/man7
    python3 jargon-mandoc.py jarg400.info --install-dir /usr/local/share/man/man7

After installation, `man jargon` works once the man directory is on MANPATH.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import os
import re
import shutil
import sys

SEP = "\x1f"  # Info node field-separator (form-feed-ish record delimiter)

# --------------------------------------------------------------------------
# Parsing the Info file
# --------------------------------------------------------------------------

_HEADER_KEYS = ("File", "Node", "Next", "Prev", "Up")


def _clean_nodename(name: str) -> str:
    """Undo Texinfo escaping that survives into node names."""
    if name is None:
        return ""
    name = name.replace("@nobrak{", "").replace("}", "")
    name = name.replace("@@", "@")
    return name.strip()


def _header_field(header: str, key: str) -> str | None:
    """Pull one `Key: value` field out of an Info node header line.

    Values run up to the next recognised key or end-of-line, which tolerates
    commas inside node names.
    """
    stop = "|".join(_HEADER_KEYS)
    m = re.search(rf"{key}:\s*(.*?)\s*(?:,\s+(?:{stop}):|$)", header)
    return m.group(1) if m else None


def parse_info(text: str) -> list[dict]:
    """Split an Info document into ordered node records."""
    nodes: list[dict] = []
    for chunk in text.split(SEP):
        chunk = chunk.lstrip("\n")
        if not chunk.strip():
            continue
        header, _, body = chunk.partition("\n")
        if not header.startswith("File:"):
            continue  # the `Info file: ...` preamble block
        nodes.append(
            {
                "name": _clean_nodename(_header_field(header, "Node")),
                "up": _clean_nodename(_header_field(header, "Up")),
                "body": body,
            }
        )
    return nodes


_LETTER_RE = re.compile(r"^=\s.+\s=$")        # `= A =`, `= [^A-Za-z] =`
_MENU_RE = re.compile(r"^\*\s.*::")           # `* Node::  description`
_UNDERLINE_RE = re.compile(r"^[*=~^-]{3,}\s*$")  # Texinfo section underlines


def classify(node: dict) -> str:
    """One of: 'entry', 'letter', 'section'."""
    if _LETTER_RE.match(node["up"] or ""):
        return "entry"
    if _LETTER_RE.match(node["name"] or ""):
        return "letter"
    return "section"


# --------------------------------------------------------------------------
# roff emission
# --------------------------------------------------------------------------


def esc(line: str) -> str:
    """Escape a source line for safe inclusion inside a `.nf` block.

    Inside no-fill text only two things bite: a literal backslash, and a
    leading `.`/`'` which roff would read as a request. Word-wrap escapes
    are unnecessary because the block is not being filled.
    """
    line = line.replace("\\", "\\e")
    if line[:1] in (".", "'"):
        line = "\\&" + line
    return line


_XREF_RE = re.compile(r"\{([^{}\n]+)\}")


def italicize_xrefs(line: str) -> str:
    """Render Jargon-style {cross-references} in italic, keeping the braces."""
    return _XREF_RE.sub(lambda m: "\\fI{" + m.group(1) + "}\\fP", line)


def strip_titlebar(body: str) -> str:
    """Drop a leading `:Title:` line + its underline from a section body.

    Texinfo renders section titles as a `:Name:` line followed by a row of
    `*`/`=`/`-`. We emit our own `.SH`/`.SS`, so those are redundant.
    """
    lines = body.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^:[^:]+:\s*$", lines[0]):
        lines.pop(0)
        if lines and _UNDERLINE_RE.match(lines[0]):
            lines.pop(0)
    return "\n".join(lines)


def drop_menus(body: str) -> str:
    """Remove Info navigation menus; they are meaningless in a man page."""
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s == "* Menu:" or _MENU_RE.match(s):
            continue
        out.append(ln)
    return "\n".join(out)


def trim_blanks(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def emit_verbatim(lines: list[str], out: list[str]) -> None:
    """Write a no-fill block, skipping empties at the edges."""
    lines = trim_blanks(list(lines))
    if not lines:
        return
    out.append(".nf")
    for ln in lines:
        out.append(italicize_xrefs(esc(ln)) or " ")
    out.append(".fi")


def emit_entry(node: dict, out: list[str]) -> None:
    """Render a lexicon entry: bold headword, verbatim definition body."""
    body = node["body"]
    m = re.match(r"\s*:([^:\n]+):", body)
    if m:
        term = m.group(1)
        rest = body[m.end():]
    else:  # malformed node: fall back to the node name
        term, rest = node["name"], body

    lines = rest.split("\n")
    # The remainder of the headword line (pronunciation, part of speech, ...)
    first = lines[0].lstrip() if lines else ""
    tail = trim_blanks(lines[1:])

    out.append(".PP")
    out.append(".nf")
    head = "\\fB" + esc(term) + "\\fP"
    if first:
        head += " " + italicize_xrefs(esc(first))
    out.append(head)
    for ln in tail:
        out.append(italicize_xrefs(esc(ln)) or " ")
    out.append(".fi")


def emit_section(node: dict, out: list[str], lexicon_open: list[bool]) -> None:
    """Render a non-lexicon node (intro, appendices, ...) as a heading + text."""
    name = node["name"]
    body = drop_menus(strip_titlebar(node["body"]))
    top_level = node["up"] in ("Top", "", None)
    macro = ".SH" if top_level else ".SS"
    out.append(f'{macro} "{name}"')
    emit_verbatim(body.split("\n"), out)
    # The lexicon proper begins right after the "The Jargon Lexicon" node.
    if name.lower() == "the jargon lexicon":
        lexicon_open[0] = True


def build_manpage(nodes: list[dict], version: str, date: str) -> str:
    out: list[str] = []
    out.append('.\\" Generated from the Jargon File Info source by jargon-mandoc.py')
    out.append(f'.TH JARGON 7 "{date}" "Jargon File {version}" "The Hacker\'s Dictionary"')
    out.append(".SH NAME")
    out.append("jargon \\- the Jargon File, a lexicon of hacker slang and folklore")
    out.append(".SH DESCRIPTION")
    out.append(
        "This page is the complete Jargon File version %s, a compendium of "
        "hacker slang, tradition, and humor. Headwords are shown in bold; "
        "terms in braces such as \\fI{foo}\\fP are cross-references to other "
        "entries in this page." % version
    )

    lexicon_open = [False]
    for node in nodes:
        if node["name"].lower() == "top":
            # The Top node is pure front matter / menu; skip its menu, keep prose.
            body = drop_menus(node["body"])
            out.append('.SH "ABOUT THIS FILE"')
            emit_verbatim(body.split("\n"), out)
            continue

        kind = classify(node)
        if kind == "letter":
            out.append(f'.SS "{node["name"]}"')
        elif kind == "entry":
            emit_entry(node, out)
        else:
            emit_section(node, out, lexicon_open)

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def detect_version(text: str) -> str:
    m = re.search(r"VERSION\s+([0-9][0-9.]*)", text)
    return m.group(1) if m else "4.0.0"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a man(7) page from the Jargon File Info source."
    )
    ap.add_argument("inputs", nargs="+", help="one or more jarg*.info files")
    ap.add_argument("-o", "--output-dir", default="./jargon-man",
                    help="directory to write jargon.7 into (default: ./jargon-man)")
    ap.add_argument("--gzip", action="store_true",
                    help="also write a gzip-compressed jargon.7.gz")
    ap.add_argument("--install", action="store_true",
                    help="install into ~/.local/share/man/man7")
    ap.add_argument("--install-dir", default=None,
                    help="install into this man7 directory instead")
    args = ap.parse_args(argv)

    # Normalize every path argument. The shell does not perform tilde
    # expansion when `~` is not word-initial (e.g. `--install-dir=~/x`), so a
    # literal `~` or `$VAR` can reach us; expand them here rather than create
    # a directory literally named `~`.
    def _norm(p: str | None) -> str | None:
        return os.path.expanduser(os.path.expandvars(p)) if p else p

    args.output_dir = _norm(args.output_dir)
    args.install_dir = _norm(args.install_dir)
    args.inputs = [_norm(p) for p in args.inputs]

    raw = ""
    for path in args.inputs:
        if not os.path.isfile(path):
            print(f"error: no such file: {path}", file=sys.stderr)
            return 1
        # latin-1 never fails to decode and preserves the file's 8-bit bytes.
        with open(path, "rb") as fh:
            raw += fh.read().decode("latin-1")

    version = detect_version(raw)
    date = _dt.date.today().isoformat()
    nodes = parse_info(raw)
    if not nodes:
        print("error: no Info nodes found -- is this a Jargon File .info build?",
              file=sys.stderr)
        return 1

    page = build_manpage(nodes, version, date)
    entries = sum(1 for n in nodes if classify(n) == "entry")

    os.makedirs(args.output_dir, exist_ok=True)
    man_path = os.path.join(args.output_dir, "jargon.7")
    with open(man_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"parsed {len(nodes)} nodes ({entries} lexicon entries)")
    print(f"wrote  {man_path}")

    if args.gzip:
        gz_path = man_path + ".gz"
        with open(man_path, "rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        print(f"wrote  {gz_path}")

    if args.install or args.install_dir:
        dest_dir = args.install_dir or os.path.expanduser(
            "~/.local/share/man/man7"
        )
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "jargon.7")
        shutil.copyfile(man_path, dest)
        print(f"installed {dest}")
        print()
        print("If `man jargon` does not find it, add the man root to MANPATH:")
        root = os.path.dirname(dest_dir)
        print(f'    export MANPATH="{root}:$(manpath)"')
        print("or run it directly:")
        print(f"    man {dest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
