from astro_daily.llm import _parse_json_text


def test_parse_json_repairs_unescaped_latex_backslashes():
    data = _parse_json_text(r'{"value": "公式 $$F_\nu \propto t^{-\alpha}$$ 和 \theta。"}')

    assert "\\nu" in data["value"]
    assert "\\alpha" in data["value"]
    assert "\\theta" in data["value"]


def test_parse_json_keeps_structural_quote_escapes():
    data = _parse_json_text('{"value": "他说：\\"ok\\""}')

    assert data["value"] == '他说："ok"'
