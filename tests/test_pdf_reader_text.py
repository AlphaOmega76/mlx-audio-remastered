"""The browser extension's PDF text cleanup (browser-extension/pdftext.js), run with Node."""

import json
import shutil
import subprocess
from pathlib import Path

NODE = shutil.which("node")  # these tests are skipped without Node
MODULE = Path(__file__).resolve().parent.parent / "browser-extension" / "pdftext.js"


def run(expr):
    """Evaluate a JS expression that uses `m` (the module); return its JSON result."""
    if not NODE:
        import pytest

        pytest.skip("Node.js is not installed")
    code = f'import("{MODULE}").then(m => console.log(JSON.stringify({expr})))'
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def paragraphs(text):
    return run(f"m.paragraphsOfPage({json.dumps(text)})")


def pages(texts):
    return run(f"m.buildPages({json.dumps(texts)})")


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
    got = paragraphs(text)
    assert len(got) == 3, got
    assert got[0].endswith("and ends here.") and got[1].startswith("The second")


def test_lines_are_joined_and_hyphenated_words_repaired():
    got = paragraphs("The harbour was quiet and the fisher-\nmen had gone home for the night to\nrest.")
    assert got == ["The harbour was quiet and the fishermen had gone home for the night to rest."], got


def test_headings_are_their_own_paragraph():
    text = (
        "Chapter Two\n"
        "The morning came in grey over the harbour, and the boats were already out beyond the\n"
        "point where the water turns dark."
    )
    got = paragraphs(text)
    assert got[0] == "Chapter Two" and got[1].startswith("The morning"), got


def test_page_numbers_and_ligatures():
    got = paragraphs("Page 3 of 40\nThe ﬁnal conﬁguration is ready.\n12")
    assert got == ["The final configuration is ready."], got


def test_running_header_and_footer_are_dropped_and_empty_pages_skipped():
    def page(n, body):
        return f"Quarterly Report\n{body}\nPrinted 5/10/26 page {n}/4"

    got = pages([page(1, "Alpha text here."), page(2, "Beta text here."), "", page(4, "Delta text here.")])
    assert [p["page"] for p in got] == [1, 2, 4], got  # page 3 had no text, numbering is kept
    flat = " ".join(" ".join(p["paragraphs"]) for p in got)
    assert "Quarterly" not in flat and "Printed" not in flat, flat
    assert "Alpha text here." in flat and "Delta text here." in flat


def test_few_pages_keep_their_first_and_last_lines():
    got = pages(["Title line\nBody one.", "Title line\nBody two."])  # only two pages: nothing is "running"
    assert "Title line" in got[0]["paragraphs"][0]


def test_junk_dot_leaders_and_repeated_phrases_are_cleaned():
    text = "Rules of the Harbour  Rules of the Harbour\nChapter 1 ����� 38\nDw\narves ........ 44\nBora Bora"
    got = paragraphs(text)
    flat = " | ".join(got)
    assert "Rules of the Harbour" in flat and "Harbour Rules" not in flat and flat.count("Rules of the Harbour") == 1, got
    assert "�" not in flat and "..." not in flat, got
    assert "Dwarves" in flat, got
    assert "Bora Bora" in flat  # a short repeat can be real, so it is kept


def test_hyphenation_with_a_space_before_the_hyphen_is_repaired():
    got = paragraphs("The humans of Eredane were once a proud and uni -\nfied people who shared a fam -\nily.")
    assert got == ["The humans of Eredane were once a proud and unified people who shared a family."], got
