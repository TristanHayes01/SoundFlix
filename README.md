# SoundFlix

SoundFlix turns a festival lineup, concert bill, or artist wish list into a playlist you can actually trust. Instead of hunting down every artist by hand—or ending up with the wrong artist who shares a name—SoundFlix verifies profiles, lets you review every suggested song, and creates a personalized discovery playlist on Spotify, TIDAL, SoundCloud, or Apple Music.





## Highlights

- Type or import an artist list, then use **Clean / Format** to split common collaborations, remove set/event noise, normalize whitespace, and remove duplicates.
- Build a lineup list with a text/CSV import, or use an image-capable AI tool such as ChatGPT or Gemini to extract artist names from a flyer and paste the resulting one-artist-per-line list into SoundFlix.
- Choose any combination of most popular songs, most recent releases, matching liked/saved songs, and matching songs from selected personal playlists. Popular and recent sources each have their own one-to-ten track count.
- Personal-library choices, selected playlists, and collaborator matching are remembered separately for each streaming service. Playlist selection offers **Select all** and **Deselect all** controls.
- Apply filters to every source, including personal-library tracks: skip remixes/edits, singles only, duplicate-title removal, rolling date windows, a selected number of years, today-to-date, or a custom date range.
- Control the number of concurrent artist-search workers in **Settings**. The builder displays progress such as `Searching 14 of 86 artists · 4 active workers`.
- If several exact-name profiles are found, SoundFlix opens a confirmation dialog while remaining searches continue. Compare profile pictures, provider links, five top-song samples, and collaborator cues; skip an artist or paste a direct profile link when needed.
- Review every candidate track before creating the playlist, with select/deselect-all controls for each artist.
- Saved service sessions are restored at startup and the first available service is selected automatically. Connection state is color-coded in the app.



## Installation

### Run from source

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

### Current platform behaviour

| Platform | Sign-in |
|---|---|
| Spotify | OAuth Authorization Code + PKCE |
| SoundCloud | OAuth 2.1 + PKCE |
| TIDAL | tidalapi browser/device login |
| Apple Music | signed developer JWT + Music User Token |

Spotify’s PKCE and playlist APIs are documented at [Spotify for Developers](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) and the [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide). SoundCloud’s OAuth 2.1 PKCE and playlist APIs are in its [API guide](https://developers.soundcloud.com/docs/api/). TIDAL’s wrapper login flow is documented by [tidalapi](https://tidalapi.netlify.app/login). Apple requires a Music User Token for library actions, and supports playlist creation via [Apple Music API](https://developer.apple.com/documentation/applemusicapi/create-a-new-library-playlist).

### Spotify

1. Create an application in the [Spotify developer dashboard](https://developer.spotify.com/dashboard).
2. Add exactly http://127.0.0.1:8765/callback to Redirect URIs.
3. Put its Client ID in SPOTIFY_CLIENT_ID. This is a desktop PKCE app, so no client secret is stored.
4. Press **Login**. The browser requests playlist modification plus saved-library and private-playlist read scopes for the optional personal-library matching feature.

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
- The shareable Windows build is designed to contain no user logins, playlist history, `.env` secrets, or private keys. Each user supplies their own credentials locally.
- Use a separate development app/credentials while testing. Never publish client secrets, private keys, or user tokens.
- A production release also needs provider approval/compliance, a privacy policy, branded provider links, token revocation/sign-out UI, and—particularly for Apple Music—a hosted MusicKit Web authorization component.

## Project map

~~~text
app/
  adapters/       BaseMusicAdapter plus Spotify, SoundCloud, TIDAL, Apple Music
  services/       TokenStore, TextCleaner, PlaylistBuilder
  ui/             CustomTkinter window plus artist, playlist, and track-review dialogs
  config.py       Environment-only configuration
  main.py         Entry point
tests/
  test_text_cleaner.py
~~~

## User flow

1. Type artist names or import a text/CSV artist list.
2. Review the editable list. **Clean / Format** splits B2B, FT., FEAT., and ampersand collaborations, removes common set noise, and deduplicates entries.
3. In **Settings**, choose song sources, counts, date/track filters, worker count, playlist description, and sign in to a streaming service. Enable personal-library matching to select liked/saved music and/or provider playlists.
4. Give the playlist a name, select a logged-in platform, and click **Build playlist**.
5. If names are ambiguous, verify the correct profiles or skip them while the rest of the catalog continues processing.
6. Review and select the resulting tracks, then create the playlist. The activity log records applied filters, unmatched artists, partial results, rate limits, expired sessions, and the playlist link.

## Extract artist names from a lineup image with AI

If you have a festival or concert flyer instead of a typed lineup, upload the image to an AI tool that can read images, such as ChatGPT, Gemini, Claude, or Copilot. Then copy the response and paste it into SoundFlix's artist list.

Use this prompt with the uploaded lineup image:

~~~text
Read this festival or concert lineup image and return only the artist names.

Rules:
- Output exactly one artist per line.
- Do not add numbering, bullet points, headings, explanations, quotes, or Markdown.
- Remove event names, dates, stage names, times, sponsors, set lengths, genre labels, and other non-artist text.
- Split collaborations such as “Artist A B2B Artist B”, “Artist A feat. Artist B”, and “Artist A & Artist B” into separate artist lines.
- Preserve the artist's normal spelling, punctuation, capitalization, and stylization when visible.
- If text is unclear, make the best reasonable reading; do not add commentary or uncertainty notes.
~~~