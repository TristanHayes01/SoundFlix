# SoundFlix

SoundFlix is a CustomTkinter desktop application that turns typed or imported artist lists into playlists. The UI stays responsive because logins, profile checks, track searches, and playlist writes run in background workers. It uses a music Platform Adapter Pattern and a standalone, testable text-cleaning service.



## Current platform behaviour

| Platform | Sign-in | “Top five” strategy |
|---|---|---|
| Spotify | OAuth Authorization Code + PKCE | Spotify removed its artist-top-tracks endpoint in February 2026. The adapter searches tracks constrained to the matched artist and ranks the results by Spotify popularity. |
| SoundCloud | OAuth 2.1 + PKCE | SoundCloud does not offer a universal artist top-track endpoint. The adapter filters the artist’s playable search results and ranks them by favorites then play count. |
| TIDAL | tidalapi browser/device login | Uses Artist.top_tracks() and tidalapi playlist creation. |
| Apple Music | signed developer JWT + Music User Token | Uses the catalog artist top-songs view, then catalog search as a fallback. |

## Highlights

- Type or import an artist list, then use **Clean / Format** to split common collaborations, remove set/event noise, normalize whitespace, and remove duplicates.
- Choose most popular songs, most recent releases, or both. Each source has its own one-to-ten track count.
- Control the number of concurrent artist-search workers in **Settings**. The builder displays progress such as `Searching 14 of 86 artists · 4 active workers`.
- If several exact-name profiles are found, SoundFlix opens a confirmation dialog while remaining searches continue.
- Review every candidate track before creating the playlist.

Spotify’s PKCE and playlist APIs are documented at [Spotify for Developers](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) and the [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide). SoundCloud’s OAuth 2.1 PKCE and playlist APIs are in its [API guide](https://developers.soundcloud.com/docs/api/). TIDAL’s wrapper login flow is documented by [tidalapi](https://tidalapi.netlify.app/login). Apple requires a Music User Token for library actions, and supports playlist creation via [Apple Music API](https://developer.apple.com/documentation/applemusicapi/create-a-new-library-playlist).

## Installation

1. Install Python 3.11 or later.
2. Open PowerShell in this directory and run:

   ~~~powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   python -m app.main
   ~~~

3. Edit .env with the credentials for only the platforms you intend to use.
4. Run tests with `pytest -q`.

## Credential setup

### Spotify

1. Create an application in the [Spotify developer dashboard](https://developer.spotify.com/dashboard).
2. Add exactly http://127.0.0.1:8765/callback to Redirect URIs.
3. Put its Client ID in SPOTIFY_CLIENT_ID. This is a desktop PKCE app, so no client secret is stored.
4. Press **Login**. The browser requests private and public playlist modification scopes.

### SoundCloud

1. Register an app on [SoundCloud](https://soundcloud.com/you/apps). Current SoundCloud documentation says obtaining API credentials requires Artist Pro.
2. Set SOUNDCLOUD_CLIENT_ID and add exactly http://127.0.0.1:8766/callback as its redirect URI.
3. Press **Login** and complete the OAuth 2.1 PKCE browser flow.

### TIDAL

1. Select TIDAL and press **Login**.
2. The tidalapi device/browser flow opens; complete it before the five-minute window expires.
3. Its refreshable session is saved in Windows Credential Manager. Check [TIDAL’s developer site](https://developer.tidal.com/) before distributing software, as API availability and registration requirements can change.

### Apple Music

1. Join the Apple Developer Program, enable MusicKit for an identifier, then create a MusicKit private key in the Apple Developer portal.
2. Set APPLE_MUSIC_TEAM_ID, APPLE_MUSIC_KEY_ID, and APPLE_MUSIC_PRIVATE_KEY_PATH in .env. Keep the .p8 key outside source control.
3. Obtain APPLE_MUSIC_USER_TOKEN from a MusicKit JS companion page or an Apple-platform app after the subscriber authorizes access. A generic Windows Python app cannot mint that token by itself; Apple’s web/Apple-platform MusicKit is the authorization surface.
4. Set the storefront (such as us) and press **Login** to validate both tokens. Creating a library playlist needs an active Apple Music subscription.

## Security

- .env, .p8 keys, and tokens are excluded by .gitignore.
- Refresh tokens are stored in the operating system credential vault through keyring (Windows Credential Manager), not a project JSON file.
- Use a separate development app/credentials while testing. Never publish client secrets, private keys, or user tokens.
- A production release also needs provider approval/compliance, a privacy policy, branded provider links, token revocation/sign-out UI, and—particularly for Apple Music—a hosted MusicKit Web authorization component.

## Project map

~~~text
app/
  adapters/       BaseMusicAdapter plus Spotify, SoundCloud, TIDAL, Apple Music
  services/       TokenStore, TextCleaner, PlaylistBuilder
  ui/             CustomTkinter window and playlist-review dialog
  config.py       Environment-only configuration
  main.py         Entry point
tests/
  test_text_cleaner.py
~~~

## User flow

1. Type artist names or import a text/CSV artist list.
2. Review the editable list. **Clean / Format** splits B2B, FT., FEAT., and ampersand collaborations, removes common set noise, and deduplicates entries.
3. In **Settings**, choose song sources, counts, filters, worker count, playlist description, and sign in to a streaming service.
4. Give the playlist a name, select a logged-in platform, and click **Build playlist**.
5. If names are ambiguous, verify the correct profiles or skip them while the rest of the catalog continues processing.
6. Review and select the resulting tracks, then create the playlist. The activity log records unmatched artists, partial results, rate limits, expired sessions, and the playlist link.
