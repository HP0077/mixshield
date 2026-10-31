import pytest

pytest.importorskip("matplotlib")

from bench import charts  # noqa: E402
from demo import results_strip  # noqa: E402


def test_strip_numbers_equal_the_chart_numbers():
    shown = results_strip.hinglish_numbers()
    chart = charts.e2_numbers()
    assert shown["ms_recall"][0] == pytest.approx(chart["MixShield screen"]["hi"]["recall"][0])
    assert shown["ms_fa"][0] == pytest.approx(chart["MixShield screen"]["hi"]["fa"][0])
    hit, n = shown["lg3_recall"]
    assert 100 * hit / n == pytest.approx(chart["Llama Guard 3"]["hi"]["recall"][0])


def test_strip_is_html_with_the_test_split_label():
    page = results_strip.strip_html()
    assert "Test split" in page and "Llama Guard 3 recall" in page and "false alarms" in page
