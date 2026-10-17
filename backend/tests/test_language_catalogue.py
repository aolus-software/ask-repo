"""The language catalogue is a wire contract: values are BCP-47 tags and never renamed."""

from app.core.language import Language


def test_the_catalogue_is_exactly_the_seven_shipped_languages() -> None:
    assert [member.value for member in Language] == [
        "en",
        "id",
        "ja",
        "ms",
        "zh-HK",
        "zh-TW",
        "ko",
    ]


def test_every_value_fits_the_column() -> None:
    assert max(len(member.value) for member in Language) <= 8
