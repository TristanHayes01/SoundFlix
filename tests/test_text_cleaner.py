from app.services.text_cleaner import TextCleaner
from app.services.playlist_builder import PlaylistBuilder, PlaylistOptions
from app.models import Artist, PlaylistResult, Track


def test_splits_collaborations_and_removes_set_noise():
    raw = "• EXCISION B2B SPACE LACES (2 HOUR SET)\nREZZ FT. GWN\nDJ SET\nA & B"
    assert TextCleaner().clean(raw) == ["EXCISION", "SPACE LACES", "REZZ", "GWN", "A", "B"]


def test_deduplicates_and_keeps_simple_artist_punctuation():
    raw = "PRESENTS\nKAYTRANADA\nkaytranada\nO'DESZA!!!\n"
    assert TextCleaner().clean(raw) == ["KAYTRANADA", "O'DESZA"]


def test_applies_general_rules_without_artist_specific_corrections():
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

    def create_playlist(self, name, tracks, description=""):
        return PlaylistResult(name, None, len(tracks))


def test_playlist_builder_uses_requested_source_and_song_count():
    adapter = _SourceSelectingAdapter()
    result = PlaylistBuilder(adapter, lambda _message: None).build(["Artist"], "New", 7, "recent")
    assert adapter.called == "recent:7"
    assert result.track_count == 1


class _CombinedSourceAdapter(_SourceSelectingAdapter):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get_top_5_tracks(self, _artist, limit):
        self.calls.append(("popular", limit))
        return [Track("popular-1", "Popular", "Artist")]

    def get_recent_tracks(self, _artist, limit):
        self.calls.append(("recent", limit))
        return [Track("recent-1", "Recent", "Artist")]


def test_playlist_builder_can_combine_popular_and_recent_tracks():
    adapter = _CombinedSourceAdapter()
    options = PlaylistOptions(include_popular=True, popular_song_count=3, include_recent=True, recent_song_count=2)
    preview = PlaylistBuilder(adapter, lambda _message: None).collect(["Artist"], options)
    assert adapter.calls == [("popular", 3), ("recent", 2)]
    assert [track.id for track in preview.tracks] == ["popular-1", "recent-1"]


class _DuplicateArtistAdapter(_SourceSelectingAdapter):
    def search_artists(self, _name):
        return [
            Artist("one", "Same Name", profile_url="https://example.test/one"),
            Artist("two", "Same Name", profile_url="https://example.test/two"),
        ]

    def get_top_5_tracks(self, artist, limit):
        return [Track(f"{artist.id}-{index}", f"Song {index}", artist.name) for index in range(1, limit + 1)]


def test_duplicate_artist_matches_include_three_song_previews_and_profile_links():
    matches, resolved = PlaylistBuilder(_DuplicateArtistAdapter(), lambda _message: None).find_ambiguous_artists(["Same Name"])
    assert resolved == {}
    assert len(matches) == 1
    assert [candidate.artist.profile_url for candidate in matches[0].candidates] == [
        "https://example.test/one", "https://example.test/two"
    ]
    assert [track.title for track in matches[0].candidates[0].sample_tracks] == ["Song 1", "Song 2", "Song 3", "Song 4", "Song 5"]


class _OnePlayableDuplicateAdapter(_DuplicateArtistAdapter):
    def get_top_5_tracks(self, artist, limit):
        if artist.id == "one":
            return []
        return super().get_top_5_tracks(artist, limit)


def test_same_name_candidates_without_songs_are_hidden_and_single_playable_match_is_used():
    matches, resolved = PlaylistBuilder(_OnePlayableDuplicateAdapter(), lambda _message: None).find_ambiguous_artists(["Same Name"])
    assert matches == []
    assert resolved["same name"].id == "two"
