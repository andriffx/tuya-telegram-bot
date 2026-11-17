"""Guard untuk aset frontend: file terpisah, tanpa inline handler, tanpa CDN, tanpa innerHTML.

Alasan: tiga hal ini yang membuat dashboard lama sulit dirawat dan rawan XSS —
1.640 baris HTML+CSS+JS dalam satu file, `onclick=` inline di mana-mana, dan
`innerHTML` yang diisi data dari API.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "tuyabot" / "static"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_assets_are_split_into_files():
    html = _text(STATIC / "index.html")
    assert 'href="/static/css/app.css"' in html
    assert 'src="/static/js/app.js"' in html
    assert '<script type="module"' in html

    for relative in ("css/app.css", "js/app.js", "js/api.js", "js/chart.js"):
        assert (STATIC / relative).is_file(), f"aset {relative} tidak ada"


def test_index_has_no_inline_event_handlers():
    html = _text(STATIC / "index.html").lower()
    for handler in ("onclick=", "onsubmit=", "onchange=", "onload="):
        assert handler not in html, f"masih ada handler inline: {handler}"


def test_no_inline_style_blocks():
    """Gaya harus di app.css, bukan <style> di dalam HTML."""
    html = _text(STATIC / "index.html").lower()
    assert "<style" not in html


def test_no_external_resources():
    """Dashboard harus jalan tanpa internet: tidak ada CDN, font, atau script eksternal."""
    html = _text(STATIC / "index.html")
    assert "https://" not in html
    # satu-satunya URL absolut yang sah adalah namespace SVG di favicon data-URI
    assert html.count("http://") == html.count("http://www.w3.org/2000/svg")


def test_javascript_does_not_use_inner_html_with_data():
    for script in (STATIC / "js").glob("*.js"):
        text = _text(script)
        assert "innerHTML" not in text, f"{script.name} memakai innerHTML — pakai textContent/el()"
        assert "outerHTML" not in text
        assert "document.write" not in text
        assert "eval(" not in text


def test_javascript_uses_text_content_helper():
    app_js = _text(STATIC / "js" / "app.js")
    assert "textContent" in app_js
    assert "addEventListener" in app_js
    assert "EventSource" in app_js, "dashboard harus memakai SSE, bukan polling terus-menerus"


def test_api_key_is_not_persisted_in_browser_storage():
    """API key lama disimpan di localStorage; sekarang harus lewat cookie HttpOnly."""
    for script in (STATIC / "js").glob("*.js"):
        text = _text(script)
        assert "localStorage" not in text, f"{script.name} masih memakai localStorage"
        assert "sessionStorage" not in text
