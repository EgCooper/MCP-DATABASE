"""HTML message bodies become compact text without markup, scripts or styles."""

import pytest

from mcp_mysql.text import body_to_text, html_to_text


def test_markup_is_removed_and_paragraphs_are_kept():
    html = ("<html><head><style>p{color:red}</style><title>Asunto</title></head><body>"
            "<p>Hola&nbsp;Juan,</p><p>Adjunto <b>el</b> log.<br>Saludos</p>"
            "<script>alert(1)</script><div>Fin &amp; más</div></body></html>")
    assert html_to_text(html) == "Hola Juan,\n\nAdjunto el log.\nSaludos\n\nFin & más"


def test_outlook_conditional_xml_and_images():
    html = '<!--[if mso]><xml><o:x>junk</o:x></xml><![endif]--><p>Texto</p><img alt="captura" src="cid:1">'
    assert html_to_text(html) == "Texto\n[captura]"


@pytest.mark.parametrize("html", ["<p>cortado <b>en medio de una etiq", "<div><p>sin cierre", "<<<>>>", ""])
def test_malformed_or_truncated_html_never_raises(html):
    assert isinstance(html_to_text(html), str)


def test_plain_text_is_only_whitespace_normalized():
    assert body_to_text("línea 1\r\n\r\n\r\n\r\nlínea   2 <b>", "text") == "línea 1\n\nlínea 2 <b>"
    assert body_to_text(None, "html") is None
    assert body_to_text("<p>a</p>", "HTML") == "a"
