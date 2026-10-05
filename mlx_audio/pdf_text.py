"""Text extraction from PDFs that draw their text twice.

Some PDFs (found in a 373-page RPG rulebook) draw every line of text two or three times at the same
spot: an outline copy under a filled copy, or a drop shadow. A PDF viewer shows one line, but a text
extractor reads each copy, so the speech repeats every sentence and word.

``page_text`` removes the repeats before extracting: a text object (``BT`` ... ``ET``) is dropped
when an earlier one on the page has the same place and the same text, ignoring colour and stroke
settings (which is what differs between the copies).

The font and other text settings of a dropped copy are kept, because in a PDF they carry over to
the next text object; dropping them made the next block decode with the wrong font and lose
letters such as "fi" and "ff".
"""

from __future__ import annotations

# Settings that differ between the copies of one text without changing what or where it is.
_STYLE_OPS = {
    "CS", "cs", "SCN", "scn", "SC", "sc", "G", "g", "RG", "rg", "K", "k",
    "w", "M", "j", "J", "d", "ri", "i", "gs", "Tr", "Tc", "Tw",
}
# What puts text on the page (and where). Everything else in a text object is a setting.
_DRAW_OPS = {"Tj", "TJ", "'", '"', "Tm", "Td", "TD", "T*"}
_SHOW_OPS = {"Tj", "TJ", "'", '"'}


def _name(op) -> str:
    return op.decode() if isinstance(op, bytes) else str(op)


def dedupe_operations(operations):
    """Return ``(operations without repeated text objects, how many were dropped)``."""
    stack = [""]  # the transformation (cm) in effect, per q/Q level: copies must share it
    seen = set()
    out = []
    block = []
    signature = []
    context = ""
    in_text = False
    removed = 0
    for operands, op in operations:
        name = _name(op)
        if in_text:
            block.append((operands, op))
            if name not in _STYLE_OPS:
                signature.append((name, tuple(str(x) for x in operands)))
            if name == "ET":
                key = (context, tuple(signature))
                if key in seen and any(s[0] in _SHOW_OPS for s in signature):
                    out.extend(b for b in block if _name(b[1]) not in _DRAW_OPS)
                    removed += 1
                else:
                    seen.add(key)
                    out.extend(block)
                in_text = False
                block = []
                signature = []
            continue
        if name == "q":
            stack.append(stack[-1])
        elif name == "Q":
            if len(stack) > 1:
                stack.pop()
        elif name == "cm":
            try:
                stack[-1] += "|" + ",".join(f"{float(x):.3f}" for x in operands)
            except (TypeError, ValueError):
                stack[-1] += "|?"
        if name == "BT":
            in_text = True
            context = stack[-1]
            block = [(operands, op)]
            signature = []
            continue
        out.append((operands, op))
    if in_text:  # unterminated text object: leave it as it was
        out.extend(block)
    return out, removed


def remove_repeated_text(reader, page) -> int:
    """Remove repeated text drawing from ``page`` (and the forms it draws). Returns how many."""
    from pypdf.generic import ContentStream

    total = 0

    def fix(obj, is_page: bool, depth: int) -> None:
        nonlocal total
        contents = page.get_contents() if is_page else obj
        if contents is not None:
            stream = ContentStream(contents, reader)
            new_ops, removed = dedupe_operations(stream.operations)
            if removed:
                total += removed
                stream.operations = new_ops
                if is_page:
                    page.replace_contents(stream)
                else:
                    obj.set_data(stream.get_data())
        if depth >= 3:
            return
        resources = (page if is_page else obj).get("/Resources")
        xobjects = resources.get_object().get("/XObject") if resources else None
        if xobjects:
            for item in xobjects.get_object().values():
                form = item.get_object()
                if form.get("/Subtype") == "/Form":
                    fix(form, False, depth + 1)

    fix(page, True, 0)
    return total


def page_text(reader, page) -> str:
    """The text of one page, with repeated drawing removed. Never fails: on any problem the page's
    text is extracted as it is."""
    try:
        remove_repeated_text(reader, page)
    except Exception:
        pass
    return (page.extract_text() or "").strip()
