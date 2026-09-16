from app.services.text_cleaner import TextCleaner
from app.services.playlist_builder import PlaylistBuilder
from app.models import Artist, PlaylistResult, Track


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


class _SourceSelectingAdapter:
    def __init__(self):
        self.called = ""

    def search_artist(self, name):
        return Artist("artist-1", name)

    def get_top_5_tracks(self, _artist, limit):
        self.called = f"popular:{limit}"
        return [Track("popular-1", "Popular", "Artist")]

    def get_recent_tracks(self, _artist, limit):
        self.called = f"recent:{limit}"
        return [Track("recent-1", "Recent", "Artist")]

    def create_playlist(self, name, tracks, description="", artwork=None):
        return PlaylistResult(name, None, len(tracks))


def test_playlist_builder_uses_requested_source_and_song_count():
    adapter = _SourceSelectingAdapter()
    result = PlaylistBuilder(adapter, lambda _message: None).build(["Artist"], "New", 7, "recent")
    assert adapter.called == "recent:7"
    assert result.track_count == 1
