from app.services.text_cleaner import TextCleaner


def test_splits_collaborations_and_removes_set_noise():
    raw = "• EXCISION B2B SPACE LACES (2 HOUR SET)\nREZZ FT. GWN\nDJ SET\nA & B"
    assert TextCleaner().clean(raw) == ["EXCISION", "SPACE LACES", "REZZ", "GWN", "A", "B"]


def test_deduplicates_and_keeps_simple_artist_punctuation():
    raw = "PRESENTS\nKAYTRANADA\nkaytranada\nO'DESZA!!!\n"
    assert TextCleaner().clean(raw) == ["KAYTRANADA", "O'DESZA"]


def test_applies_general_ocr_rules_without_artist_specific_corrections():
    raw = "1\nEXCISION EXCISION BZB SPACE LACES\nDOCTOR P DR. FRESCH\nCULTURE SHOCK"
    assert TextCleaner().clean(raw) == [
        "EXCISION", "SPACE LACES", "DOCTOR P DR. FRESCH", "CULTURE SHOCK"
    ]
