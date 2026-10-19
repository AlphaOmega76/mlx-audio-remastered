"""The web app's matching of spoken sentences to places on PDF pages (mlx_audio/ui/utils/pdf-align.ts),
run with Node (it reads the TypeScript directly)."""

import json
import shutil
import subprocess
from pathlib import Path

NODE = shutil.which("node")  # these tests are skipped without Node
MODULE = Path(__file__).resolve().parent.parent / "mlx_audio" / "ui" / "utils" / "pdf-align.ts"


def align(sentences, pages):
    """pages: a list of pages, each a list of (text, x, y, width) items drawn 10 units high."""
    if not NODE:
        import pytest

        pytest.skip("Node.js is not installed")
    items = [[{"str": s, "x": x, "y": y, "w": w, "h": 10} for (s, x, y, w) in page] for page in pages]
    code = f'import("{MODULE}").then(m => console.log(JSON.stringify(m.alignSentences({json.dumps(sentences)}, {json.dumps(items)}))))'
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_sentence_gets_the_part_of_the_line_it_covers():
    # "Hello there. General Kenobi." is one 280-unit line: each sentence gets about half of it
    r = align(["Hello there.", "General Kenobi."], [[("Hello there. General Kenobi.", 50, 700, 280)]])
    assert [len(x) for x in r] == [1, 1]
    first, second = r[0][0], r[1][0]
    assert first["x"] == 50 and 0 < first["w"] < 280 and second["x"] > first["x"] + first["w"] - 1
    assert abs(first["w"] + second["w"] - 280) < 1e-6


def test_a_sentence_over_two_lines_gets_two_rectangles_in_order():
    r = align(["The quick brown fox jumps over the lazy dog."],
              [[("The quick brown fox jumps", 50, 700, 120), ("over the lazy dog.", 50, 686, 90)]])
    assert [(x["page"], x["y"]) for x in r[0]] == [(0, 700), (0, 686)]


def test_text_drawn_twice_in_the_same_place_is_used_once():
    line = ("Every line here is drawn two times.", 50, 700, 170)
    r = align(["Every line here is drawn two times."], [[line, line]])
    assert len(r[0]) == 1


def test_a_sentence_that_is_not_on_any_page_gets_nothing_and_the_rest_still_match():
    r = align(["First one is here.", "This is nowhere on the page at all.", "Last one is here too."],
              [[("First one is here.", 50, 700, 90), ("Last one is here too.", 50, 686, 100)]])
    assert [len(x) for x in r] == [1, 0, 1]
    assert r[2][0]["y"] == 686


def test_ligatures_and_punctuation_do_not_stop_a_match():
    r = align(["The first office finished the benefit."], [[("The ﬁrst oﬃce ﬁnished the beneﬁt!", 50, 700, 200)]])
    assert len(r[0]) == 1


def test_repeated_sentences_match_in_reading_order():
    r = align(["Same words again.", "Same words again."],
              [[("Same words again.", 50, 700, 90)], [("Same words again.", 50, 700, 90)]])
    assert [x[0]["page"] for x in r] == [0, 1]


def test_sentences_match_across_pages():
    r = align(["Opening sentence of page one.", "Closing sentence on page two."],
              [[("Opening sentence of page one.", 50, 700, 140)], [("Closing sentence on page two.", 50, 700, 140)]])
    assert [x[0]["page"] for x in r] == [0, 1]


def test_a_small_difference_in_the_page_text_still_matches_by_beginning_and_end():
    # a footnote number sits inside the sentence on the page but not in the cleaned text
    r = align(["The old harbour wall covered in green weed stood firm against the waves."],
              [[("The old harbour wall 12 covered in green weed stood firm against the waves.", 50, 700, 300)]])
    assert len(r[0]) == 1


def test_empty_input_is_fine():
    assert align([], [[]]) == []
    assert align(["Nothing to find."], []) == [[]]
