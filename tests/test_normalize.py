import pytest

from mixshield.normalize import HINGLISH_VARIANTS, normalize

# Fixed values of the 10 goals that must never change (IBANs, emails, URLs, numbers), plus a few look-alikes.
FIXED_VALUES = [
    "US133000000121212121212",
    "mark.black-2134@gmail.com",
    "security@facebook.com",
    "lily.white@gmail.com",
    "www.secure-systems-252.com",
    "www.my-website-234.com/random",
    "$30,000",
    "$10,000",
    "DE89370400440532013000",
    "Mark.Black@Gmail.COM",
    "https://WWW.Example.com/Path",
    "secure-systems-252.com",
    "₹1,250.50",
]


def test_nfc():
    assert normalize("café") == "café"


def test_invisible_characters_removed():
    assert normalize("pay​me‍ now﻿") == "payme now"
    assert normalize("bhe‌jo") == "bhejo"


def test_unusual_spaces_and_repeats_collapse():
    assert normalize("a  b \t c") == "a b c"
    assert normalize("  line one  \n  line two ") == "line one\nline two"


def test_only_latin_is_lowercased():
    assert normalize("Hello पैसे भेजो Привет") == "hello पैसे भेजो Привет"


@pytest.mark.parametrize("variant, form", [(v, f) for f, vs in HINGLISH_VARIANTS.items() for v in vs])
def test_every_variant_maps_to_its_form(variant, form):
    assert normalize(f"aap {variant} yaar") == f"aap {form} yaar"


def test_hinglish_sentence():
    assert normalize("Jldi se transfer KRDO aur paise bhej do") == "jaldi se transfer karo aur paise bhejo"
    assert normalize("kar   do") == "karo"


def test_parts_of_words_are_not_mapped():
    assert normalize("krdo123 abiding kroner") == "krdo123 abiding kroner"
    assert normalize("kar") == "kar"
    assert normalize("bhej diya") == "bhej diya"


@pytest.mark.parametrize("value", FIXED_VALUES)
def test_fixed_values_survive_unchanged(value):
    text = f"Plz jldi {value} pe transfer kro"
    out = normalize(text)
    assert value in out
    assert out == f"please jaldi {value} pe transfer karo"


def test_fixed_value_with_variant_inside_is_untouched():
    for value in ["kro@site.com", "www.kro-shop.com", "plz.io", "msg.in/abhii"]:
        assert normalize(f"send {value}") == f"send {value}"


def test_hidden_character_inside_a_fixed_value_is_removed():
    assert normalize("US1330000001212​12121212") == "US133000000121212121212"


def test_devanagari_unchanged():
    text = "कृपया तुरंत पैसे भेजें"
    assert normalize(text) == text


def test_idempotent():
    text = "Plz  JLDI kar do​, send $30,000 to US133000000121212121212 www.My-Site.com"
    assert normalize(normalize(text)) == normalize(text)
