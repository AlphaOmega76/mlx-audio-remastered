"""Removing text that a PDF draws several times at the same spot (mlx_audio/pdf_text.py)."""

import io

import pytest

pytest.importorskip("pypdf")

from pypdf import PdfReader

from mlx_audio.pdf_text import dedupe_operations, page_text


def _pdf(content: str) -> bytes:
    """A one-page PDF whose page content is `content` (fonts F1 = Helvetica, F2 = Times)."""
    stream = content.encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def _text(content: str) -> str:
    reader = PdfReader(io.BytesIO(_pdf(content)))
    return page_text(reader, reader.pages[0])


# an outline copy (stroke, dark) and a filled copy (white) of the same words at the same place
OUTLINE_AND_FILL = (
    "BT /F1 12 Tf 1 Tr 0.1 0.1 0.1 rg 50 250 Td (Hello brave world) Tj ET\n"
    "BT /F1 12 Tf 0 Tr 1 1 1 rg 50 250 Td (Hello brave world) Tj ET\n"
)


def test_text_drawn_twice_is_read_once():
    assert PdfReader(io.BytesIO(_pdf(OUTLINE_AND_FILL))).pages[0].extract_text().count("Hello brave world") == 2
    assert _text(OUTLINE_AND_FILL) == "Hello brave world"


def test_same_words_in_different_places_are_both_kept():
    content = (
        "BT /F1 12 Tf 50 250 Td (Echo) Tj ET\n"
        "BT /F1 12 Tf 50 200 Td (Echo) Tj ET\n"  # same words, a different line
    )
    assert _text(content).split() == ["Echo", "Echo"]


def test_dropped_copy_keeps_its_settings_for_the_next_block():
    # The second block repeats the first (only its spacing and render mode differ) and sets a character
    # spacing that carries on to the third block, so that setting must survive although the drawing goes.
    content = (
        "BT /F1 12 Tf 1 Tr 50 250 Td (Alpha) Tj ET\n"
        "BT /F1 12 Tf 0 Tr 2 Tc 50 250 Td (Alpha) Tj ET\n"
        "BT 50 200 Td (Beta) Tj ET\n"
    )
    from pypdf.generic import ContentStream

    reader = PdfReader(io.BytesIO(_pdf(content)))
    ops, removed = dedupe_operations(ContentStream(reader.pages[0].get_contents(), reader).operations)
    assert removed == 1
    names = [(op.decode() if isinstance(op, bytes) else op) for _, op in ops]
    assert names.count("Tj") == 2  # Alpha once, Beta once
    assert any((op.decode() if isinstance(op, bytes) else op) == "Tc" and float(args[0]) == 2 for args, op in ops)
    assert _text(content).split() == ["Alpha", "Beta"]


def test_text_in_a_transformed_context_is_not_a_repeat():
    content = (
        "q BT /F1 12 Tf 50 250 Td (Same) Tj ET Q\n"
        "q 1 0 0 1 0 -50 cm BT /F1 12 Tf 50 250 Td (Same) Tj ET Q\n"  # same operations, moved down
    )
    assert _text(content).split() == ["Same", "Same"]


def test_a_broken_page_still_gives_its_text():
    class Boom:
        def get_contents(self):
            raise RuntimeError("boom")

        def extract_text(self):
            return " plain text "

    assert page_text(None, Boom()) == "plain text"


# ---- paragraphs (mirrors tests/test_pdf_reader_text.py, which tests the extension's JavaScript version) ----

from mlx_audio.pdf_text import build_pages, format_text, paragraphs_of_page


def test_blank_line_and_short_last_line_end_a_paragraph():
    text = (
        "This is the first paragraph and its lines run right out to the margin of the\n"
        "page like ordinary justified body text does in a book or a report that is long\n"
        "and ends here.\n"
        "The second paragraph starts on a fresh line and keeps going out to the margin of\n"
        "the page just the same as the first one did before it stopped.\n"
        "\n"
        "A third one, after a blank line."
    )
    got = paragraphs_of_page(text)
    assert len(got) == 3, got
    assert got[0].endswith("and ends here.") and got[1].startswith("The second")


def test_lines_are_joined_and_hyphenated_words_repaired():
    assert paragraphs_of_page("The harbour was quiet and the fisher-\nmen had gone home for the night to\nrest.") == [
        "The harbour was quiet and the fishermen had gone home for the night to rest."
    ]
    # a space before the hyphen, and trailing spaces that PDF extraction leaves at the end of lines
    got = paragraphs_of_page("The humans of Eredane were once a proud and uni -  \nfied people who shared a fam -  \nily.")
    assert got == ["The humans of Eredane were once a proud and unified people who shared a family."], got


def test_headings_are_their_own_paragraph():
    got = paragraphs_of_page(
        "Chapter Two\nThe morning came in grey over the harbour, and the boats were already out beyond the\n"
        "point where the water turns dark."
    )
    assert got[0] == "Chapter Two" and got[1].startswith("The morning"), got


def test_page_numbers_ligatures_junk_leaders_and_repeated_phrases():
    assert paragraphs_of_page("Page 3 of 40\nThe ﬁnal conﬁguration is ready.\n12") == ["The final configuration is ready."]
    flat = " | ".join(
        paragraphs_of_page("Rules of the Harbour  Rules of the Harbour\nChapter 1 ����� 38\nDw\narves ........ 44\nBora Bora")
    )
    assert flat.count("Rules of the Harbour") == 1 and "�" not in flat and "..." not in flat
    assert "Dwarves" in flat and "Bora Bora" in flat


def test_running_header_and_footer_dropped_and_empty_pages_skipped():
    def page(n, body):
        return f"Quarterly Report\n{body}\nPrinted 5/10/26 page {n}/4"

    got = build_pages([page(1, "Alpha text here."), page(2, "Beta text here."), "", page(4, "Delta text here.")])
    assert [n for n, _ in got] == [1, 2, 4]
    flat = " ".join(" ".join(p) for _, p in got)
    assert "Quarterly" not in flat and "Printed" not in flat and "Alpha text here." in flat


def test_formatted_text_has_blank_lines_between_paragraphs_and_joins_across_pages():
    pages = [
        (1, ["First paragraph ends here.", "Second paragraph runs on and on until the page"]),
        (2, ["ends and carries on onto the next page.", "Third paragraph."]),
    ]
    assert format_text(pages) == (
        "First paragraph ends here.\n\n"
        "Second paragraph runs on and on until the page ends and carries on onto the next page.\n\n"
        "Third paragraph."
    )


def test_extracted_pdf_text_comes_out_as_paragraphs():
    # a PDF whose lines are padded and broken the way real ones are
    lines = ["(Alpha line one of the first paragraph runs to the margin of the page and on) '",
             "(and a short end.) '",
             "(Beta line one of the second paragraph also runs right out to the page margin and) '",
             "(ends too.) '"]
    content = "BT /F1 12 Tf 14 TL 20 250 Td\n" + "\n".join(lines) + "\nET"
    reader = PdfReader(io.BytesIO(_pdf(content)))
    text = format_text(build_pages([page_text(reader, reader.pages[0])]))
    assert text.count("\n\n") == 1 and "\n" not in text.replace("\n\n", ""), repr(text)
