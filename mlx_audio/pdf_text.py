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


# ---- paragraphs --------------------------------------------------------------------------------
# PDF text has a hard line break at the end of every visual line (often padded with spaces), no
# paragraph markers, and page numbers, running headers and junk characters in between. This rebuilds
# readable paragraphs with a few simple rules. It is a heuristic (a PDF has no real paragraphs), and
# mirrors browser-extension/pdftext.js, which does the same for the extension's PDF reader page.
#
#   * a blank line is a paragraph break
#   * a line that ends a sentence and is clearly shorter than the page's full lines ends its paragraph
#   * a short line without end punctuation, followed by a capitalised line, is a heading
#   * a word split by a hyphen at the end of a line, or cut after 1-3 letters, is joined back together
#   * page numbers, running headers/footers, junk characters and dot leaders are dropped
#   * ligatures such as "ﬁ" become plain letters; a phrase repeated within one line is collapsed

import math
import re
import unicodedata

_SENTENCE_END = re.compile(r"""[.!?:;…]["'”’)\]]*$""")
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE)
_REPEAT = re.compile(r"^(.{10,}?)\s*\1$")
_EDGE = 2  # lines at the top and bottom of a page that may be a running header or footer


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in unicodedata.normalize("NFKC", text or "").splitlines():
        line = re.sub(r"�+", " ", raw)
        line = re.sub(r"[.…]{4,}", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        m = _REPEAT.match(line)
        lines.append(m.group(1) if m else line)
    return lines


def _shape(line: str) -> str:
    return re.sub(r"\d+", "#", line)


def _running_lines(page_texts: list[str]) -> set[str]:
    """Lines that, ignoring digits, open or close at least half of the pages (3 or more pages)."""
    if len(page_texts) < 3:
        return set()
    counts: dict[str, int] = {}
    for text in page_texts:
        lines = [l for l in _clean_lines(text) if l]
        for shape in {_shape(l) for l in lines[:_EDGE] + lines[-_EDGE:]}:
            counts[shape] = counts.get(shape, 0) + 1
    need = max(2, math.ceil(len(page_texts) / 2))
    return {s for s, n in counts.items() if n >= need and any(c.isalpha() for c in s)}


def _join(prev: str, nxt: str, last_len: int) -> str:
    if re.search(r"[A-Za-z] ?-$", prev) and re.match(r"[a-z]", nxt):
        return re.sub(r" ?-$", "", prev) + nxt
    if last_len <= 3 and re.search(r"[A-Za-z]$", prev) and re.match(r"[a-z]", nxt):
        return prev + nxt
    return prev + " " + nxt


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


def paragraphs_of_page(text: str, drop: set[str] | None = None) -> list[str]:
    """One page's text -> a list of paragraph strings. ``drop`` = running header/footer shapes."""
    lines = _clean_lines(text)
    if drop:
        filled = [i for i, l in enumerate(lines) if l]
        edge = set(filled[:_EDGE] + filled[-_EDGE:])
        lines = ["" if (i in edge and _shape(l) in drop) else l for i, l in enumerate(lines)]
    full = _percentile([len(l) for l in lines if l], 0.9)

    out: list[str] = []
    cur = ""
    last_len = 0

    def flush() -> None:
        nonlocal cur, last_len
        if cur:
            out.append(cur)
        cur = ""
        last_len = 0

    for line in lines:
        if not line:
            flush()
            continue
        if _PAGE_NUMBER.match(line):
            continue
        if cur:
            short_line = last_len < 0.75 * full
            ends_sentence = bool(_SENTENCE_END.search(cur))
            heading = last_len < 0.5 * full and last_len < 70 and not ends_sentence and re.match(r"[A-Z0-9]", line)
            if (ends_sentence and short_line) or heading:
                flush()
        cur = _join(cur, line, last_len) if cur else line
        last_len = len(line)
    flush()
    return out


def build_pages(page_texts: list[str]) -> list[tuple[int, list[str]]]:
    """All pages -> ``[(page number from 1, [paragraphs])]``, skipping pages with no text."""
    drop = _running_lines(page_texts)
    pages = []
    for i, text in enumerate(page_texts):
        paragraphs = paragraphs_of_page(text, drop)
        if paragraphs:
            pages.append((i + 1, paragraphs))
    return pages


def format_text(pages: list[tuple[int, list[str]]]) -> str:
    """Paragraphs separated by blank lines. A paragraph that runs on across a page break (it does not
    end a sentence and the next page begins in lower case) is joined into one."""
    paragraphs: list[str] = []
    for _, page in pages:
        for k, paragraph in enumerate(page):
            if k == 0 and paragraphs and not _SENTENCE_END.search(paragraphs[-1]) and re.match(r"[a-z]", paragraph):
                paragraphs[-1] = _join(paragraphs[-1], paragraph, len(paragraphs[-1]))
            else:
                paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)
