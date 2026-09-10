from .spotify import SpotifyAdapter
from .soundcloud import SoundCloudAdapter
from .tidal import TidalAdapter
from .apple_music import AppleMusicAdapter

ADAPTERS = {
    "Spotify": SpotifyAdapter,
    "SoundCloud": SoundCloudAdapter,
    "TIDAL": TidalAdapter,
    "Apple Music": AppleMusicAdapter,
}
