import io

import pytest

pytest.importorskip("pypdf")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from mlx_audio import server


def _text_pdf(text: str) -> bytes:
    """Build a minimal single-page PDF with a text layer."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objs[3] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
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
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objs) + 1, xref)
    )
    return out.getvalue()


def _blank_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


def _post(client, data, name="doc.pdf"):
    return client.post(
        "/v1/documents/extract-text",
        files={"file": (name, data, "application/pdf")},
    )


def test_extracts_text(client):
    r = _post(client, _text_pdf("Hello MLX Audio"))
    assert r.status_code == 200
    body = r.json()
    assert "Hello MLX Audio" in body["text"]
    assert body["pages"] == 1
    assert body["filename"] == "doc.pdf"


def test_rejects_non_pdf(client):
    assert _post(client, b"just some text", "a.txt").status_code == 400


def test_no_text_layer_returns_422(client):
    assert _post(client, _blank_pdf()).status_code == 422
