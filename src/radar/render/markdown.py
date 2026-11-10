"""Write a Document as GitHub-flavoured Markdown."""
from __future__ import annotations

from pathlib import Path

from .blocks import Bullets, Card, Code, Document, Heading, Image, Inline, Link, Para, Ref, Table


def _inline(x: Inline) -> str:
    if isinstance(x, Link):
        return f"[{x.text}]({x.url})"
    if isinstance(x, Ref):
        return f"[{x.text}](#{x.anchor})"
    return x


def _cell(x: Inline) -> str:
    return _inline(x).replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[Inline]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out


def to_markdown(doc: Document, out_dir: Path) -> str:
    lines = [f"# {doc.title}", "", doc.subtitle, ""]
    for b in doc.blocks:
        if isinstance(b, Heading):
            if b.anchor:
                lines.append(f'<a id="{b.anchor}"></a>')
            lines += ["#" * (b.level + 1) + " " + b.text, ""]
        elif isinstance(b, Para):
            lines += [f"*{b.text}*" if b.muted else b.text, ""]
        elif isinstance(b, Bullets):
            lines += [f"- {'**' + p + '**' if p else ''}{_inline(c)}" for p, c in b.items] + [""]
        elif isinstance(b, Table):
            lines += _table(b.headers, b.rows) + [""]
            if b.caption:
                lines += [f"*{b.caption}*", ""]
        elif isinstance(b, Card):
            lines += _table(["项目", "内容"], [[k, v] for k, v in b.rows]) + [""]
        elif isinstance(b, Image):
            rel = b.path.relative_to(out_dir) if b.path.is_relative_to(out_dir) else b.path
            lines += [f"![{b.caption}]({rel.as_posix()})", ""]
            if b.caption:
                lines += [f"*{b.caption}*", ""]
        elif isinstance(b, Code):
            lines += ["```text", b.text, "```", ""]
    return "\n".join(lines).rstrip() + "\n"
