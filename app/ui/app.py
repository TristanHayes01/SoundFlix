"""Modern CustomTkinter UI. All slow work runs in daemon workers and reports via after()."""
from __future__ import annotations
import threading
import traceback
import csv
from datetime import date, datetime
import tkinter.filedialog as filedialog
import customtkinter as ctk

from app.adapters import ADAPTERS
from app.config import settings
from app.services.playlist_builder import ArtistCandidate, PlaylistBuilder, PlaylistOptions
from app.services.text_cleaner import TextCleaner
from app.services.token_store import TokenStore
from .artist_match_dialog import ArtistMatchDialog
from .library_playlist_dialog import LibraryPlaylistDialog
from .review_dialog import PlaylistReviewDialog

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

CONNECTED = "#2fa572"
DISCONNECTED = "#a7adb8"
WORKING = "#e5a93d"


class SoundFlixApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SoundFlix")
        self.geometry("1120x760")
        self.minsize(900, 650)
        self._busy = False
        self.token_store = TokenStore()
        saved = self.token_store.load("preferences") or {}
        legacy_count = str(saved.get("songs_per_artist", 5))
        legacy_source = saved.get("track_source", "Most popular songs")
        self.include_popular = ctk.BooleanVar(value=saved.get("include_popular", legacy_source != "Most recent releases"))
        self.popular_song_count = ctk.StringVar(value=str(saved.get("popular_song_count", legacy_count)))
        self.include_recent = ctk.BooleanVar(value=saved.get("include_recent", legacy_source == "Most recent releases"))
        self.recent_song_count = ctk.StringVar(value=str(saved.get("recent_song_count", legacy_count)))
        self.artist_thread_count = ctk.StringVar(value=str(saved.get("artist_thread_count", 4)))
        self.release_window = ctk.StringVar(value=saved.get("release_window", "Any release date"))
        self.custom_release_start = ctk.StringVar(value=saved.get("custom_release_start", ""))
        self.custom_release_end = ctk.StringVar(value=saved.get("custom_release_end", ""))
        self.release_years = ctk.StringVar(value=str(saved.get("release_years", 1)))
        self.skip_remixes = ctk.BooleanVar(value=saved.get("skip_remixes", False))
        self.singles_only = ctk.BooleanVar(value=saved.get("singles_only", False))
        self.dedupe_titles = ctk.BooleanVar(value=saved.get("dedupe_titles", True))
        self.library_preferences: dict[str, dict] = saved.get("library_preferences", {})
        self.include_library = ctk.BooleanVar(value=False)
        self.include_liked_tracks = ctk.BooleanVar(value=False)
        self.include_playlist_tracks = ctk.BooleanVar(value=False)
        self.include_library_collaborations = ctk.BooleanVar(value=True)
        self._loading_library_preferences = False
        # A newly installed app gets a branded default; a user's saved edit always wins.
        self.playlist_description = ctk.StringVar(
            value=saved["playlist_description"]
            if "playlist_description" in saved else "Made with SoundFlix"
        )
        self.auth_buttons: list[ctk.CTkButton] = []
        self.service_status: dict[str, ctk.CTkLabel] = {}
        self.connection_state: dict[str, bool | None] = {name: False for name in ADAPTERS}
        self._startup_platform_selected = False
        self._artist_match_dialog: ArtistMatchDialog | None = None
        self._library_playlist_dialog: LibraryPlaylistDialog | None = None
        self._temporary_error_dialog: ctk.CTkToplevel | None = None
        self._build()
        self._load_library_preferences("Spotify")
        self.playlist_description.trace_add("write", self._save_playlist_description)
        # Restore existing local sessions after the window is visible. Services with no saved
        # session are left alone, avoiding four unexpected browser authorization windows.
        self.after(300, self.restore_saved_sessions)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self); top.grid(row=0, column=0, padx=14, pady=(14, 8), sticky="ew")
        top.grid_columnconfigure(5, weight=1)
        ctk.CTkLabel(top, text="SoundFlix", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, padx=14, pady=12)
        self.platform = ctk.StringVar(value="Spotify")
        ctk.CTkOptionMenu(top, values=list(ADAPTERS), variable=self.platform).grid(row=0, column=1, padx=8)
        self.generate_button = ctk.CTkButton(top, text="Build playlist", command=self.generate); self.generate_button.grid(row=0, column=2, padx=8)
        self.selected_service_indicator = ctk.CTkLabel(top, text="Spotify: Not logged in", text_color=DISCONNECTED)
        self.selected_service_indicator.grid(row=0, column=3, padx=8)
        self.platform.trace_add("write", self._selected_platform_changed)

        tabs = ctk.CTkTabview(self); tabs.grid(row=1, column=0, padx=14, pady=8, sticky="nsew")
        builder_tab = tabs.add("Playlist builder")
        settings_tab = tabs.add("Settings")
        history_tab = tabs.add("History")
        builder_tab.grid_columnconfigure((0, 1), weight=1, uniform="columns")
        builder_tab.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(builder_tab); left.grid(row=0, column=0, padx=(0, 7), pady=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(left, text="1. Add artist names", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=14, pady=(14, 8), sticky="w")
        buttons = ctk.CTkFrame(left, fg_color="transparent")
        buttons.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        buttons.grid_columnconfigure((0, 1), weight=1, uniform="artist_actions")
        ctk.CTkButton(buttons, text="Import artists", command=self.import_artists).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(buttons, text="Export artists", command=self.export_artists).grid(row=0, column=1, padx=(4, 0), sticky="ew")
        self.review = ctk.CTkTextbox(left, wrap="word"); self.review.grid(row=2, column=0, padx=14, pady=8, sticky="nsew")
        self._artist_counter_job = None
        self.review.bind("<<Modified>>", self._artist_text_changed)
        footer = ctk.CTkFrame(left, fg_color="transparent"); footer.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="ew")
        ctk.CTkButton(footer, text="Clean / Format", command=self.clean_text).pack(side="left")
        ctk.CTkLabel(footer, text="One artist per line. You can edit freely.").pack(side="left", padx=10)
        self.artist_counter = ctk.CTkLabel(footer, text="Artist lines: 0", text_color=DISCONNECTED)
        self.artist_counter.pack(side="right")

        right = ctk.CTkFrame(builder_tab); right.grid(row=0, column=1, padx=(7, 0), pady=0, sticky="nsew")
        right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(right, text="2. Playlist details and activity", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=14, pady=(14, 8), sticky="w")
        self.playlist_name = ctk.CTkEntry(right, placeholder_text="Playlist name (for example: Lost Lands lineup)"); self.playlist_name.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        self.log_box = ctk.CTkTextbox(right, state="disabled", wrap="word"); self.log_box.grid(row=2, column=0, padx=14, pady=8, sticky="nsew")
        log_controls = ctk.CTkFrame(right, fg_color="transparent"); log_controls.grid(row=3, column=0, padx=14, pady=(0, 6), sticky="ew")
        ctk.CTkButton(log_controls, text="Copy log", width=100, command=self.copy_log).pack(side="left")
        ctk.CTkButton(log_controls, text="Clear log", width=100, command=self.clear_log).pack(side="left", padx=8)
        progress = ctk.CTkFrame(right, fg_color="transparent")
        progress.grid(row=4, column=0, padx=14, pady=(0, 14), sticky="ew")
        progress.grid_columnconfigure(1, weight=1)
        self.search_progress_label = ctk.CTkLabel(
            progress, text="Ready to search", text_color=DISCONNECTED, anchor="w"
        )
        self.search_progress_label.grid(row=0, column=0, padx=(0, 10), sticky="w")
        self.search_progress = ctk.CTkProgressBar(progress)
        self.search_progress.grid(row=0, column=1, sticky="ew")
        self.search_progress.set(0)
        self._build_settings(settings_tab)
        self._build_history(history_tab)

    def _build_history(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1); parent.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(parent, fg_color="transparent"); header.grid(row=0, column=0, padx=20, pady=(20, 8), sticky="ew")
        ctk.CTkLabel(header, text="Playlist history", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Refresh", width=90, command=self.refresh_history).pack(side="right")
        self.history_list = ctk.CTkScrollableFrame(parent)
        self.history_list.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.refresh_history()

    def refresh_history(self) -> None:
        for child in self.history_list.winfo_children():
            child.destroy()
        history = self.token_store.load("playlist_history") or []
        if not history:
            ctk.CTkLabel(self.history_list, text="No SoundFlix playlists have been created yet.").pack(anchor="w", padx=8, pady=8)
            return
        for item in history:
            row = ctk.CTkFrame(self.history_list)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"{item['name']}  •  {item['platform']}  •  {item['tracks']} tracks", anchor="w").pack(side="left", padx=10, pady=9)
            if item.get("artists"):
                ctk.CTkButton(row, text="Copy artists", width=100,
                              command=lambda artists=item["artists"]: self._copy_text("\n".join(artists))).pack(side="right", padx=4)
            if item.get("url"):
                ctk.CTkButton(row, text="Copy link", width=80, command=lambda url=item["url"]: self._copy_text(url)).pack(side="right", padx=8)

    def _copy_text(self, text: str) -> None:
        self.clipboard_clear(); self.clipboard_append(text); self.update()

    def _build_settings(self, parent) -> None:
        """Build a grouped Settings view with an explicit, usable scroll area."""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        content = ctk.CTkScrollableFrame(
            parent,
            height=520,
            scrollbar_fg_color="#303846",
            scrollbar_button_color="#2fa572",
            scrollbar_button_hover_color="#23865d",
        )
        content.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(content, text="1 · Playlist selection", font=ctk.CTkFont(size=18, weight="bold"), text_color="#7bdcb5").grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(content, text="Choose what SoundFlix finds for each artist. These choices are saved automatically.", text_color=DISCONNECTED).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")
        popular_frame = ctk.CTkFrame(content)
        popular_frame.grid(row=2, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkCheckBox(popular_frame, text="Include most popular songs", variable=self.include_popular, command=self._save_song_preference).pack(side="left", padx=14, pady=14)
        ctk.CTkLabel(popular_frame, text="How many").pack(side="left", padx=(20, 4))
        ctk.CTkOptionMenu(popular_frame, values=[str(n) for n in range(1, 11)], variable=self.popular_song_count, command=self._save_song_preference).pack(side="left", padx=4)

        recent_frame = ctk.CTkFrame(content)
        recent_frame.grid(row=3, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkCheckBox(recent_frame, text="Include most recent releases", variable=self.include_recent, command=self._save_song_preference).pack(side="left", padx=14, pady=14)
        ctk.CTkLabel(recent_frame, text="How many").pack(side="left", padx=(20, 4))
        ctk.CTkOptionMenu(recent_frame, values=[str(n) for n in range(1, 11)], variable=self.recent_song_count, command=self._save_song_preference).pack(side="left", padx=4)

        library_frame = ctk.CTkFrame(content)
        library_frame.grid(row=4, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkCheckBox(library_frame, text="Add matching tracks from my music library", variable=self.include_library,
                         command=self._library_source_changed).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        self.library_credits_frame = ctk.CTkFrame(library_frame, fg_color="#252b35")
        self.library_credits_frame.grid(row=1, column=0, columnspan=2, padx=34, pady=(2, 8), sticky="ew")
        self.library_credits_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.library_credits_frame, text="Artist credit matching", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=12, pady=(9, 0), sticky="w"
        )
        ctk.CTkLabel(self.library_credits_frame, text="Include songs where a lineup artist is featured, not only the primary artist.",
                     text_color=DISCONNECTED).grid(row=1, column=0, padx=12, pady=(0, 9), sticky="w")
        self.library_collaborators_check = ctk.CTkSwitch(
            self.library_credits_frame, text="Match collaborators", variable=self.include_library_collaborations,
            command=self._save_library_preferences,
        )
        self.library_collaborators_check.grid(row=0, column=1, rowspan=2, padx=12, pady=10, sticky="e")
        self.library_liked_check = ctk.CTkCheckBox(library_frame, text="Liked / saved songs", variable=self.include_liked_tracks,
                                                   command=self._save_library_preferences)
        self.library_liked_check.grid(row=2, column=0, padx=34, pady=4, sticky="w")
        self.library_playlists_check = ctk.CTkCheckBox(library_frame, text="Selected playlists", variable=self.include_playlist_tracks,
                                                       command=self._playlist_source_changed)
        self.library_playlists_check.grid(row=3, column=0, padx=34, pady=4, sticky="w")
        self.choose_library_playlists_button = ctk.CTkButton(library_frame, text="Choose playlists", width=130,
                                                              command=self.choose_library_playlists)
        self.choose_library_playlists_button.grid(row=3, column=1, padx=8, pady=4)
        self.library_playlist_summary = ctk.CTkLabel(library_frame, text="No playlists selected", text_color=DISCONNECTED, anchor="w")
        self.library_playlist_summary.grid(row=4, column=0, columnspan=2, padx=34, pady=(2, 12), sticky="w")

        workers_frame = ctk.CTkFrame(content)
        workers_frame.grid(row=5, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkLabel(workers_frame, text="Artist search workers").pack(side="left", padx=14, pady=14)
        ctk.CTkOptionMenu(workers_frame, values=["1", "2", "4", "6", "8"], variable=self.artist_thread_count, command=self._save_song_preference).pack(side="left", padx=8)
        ctk.CTkLabel(workers_frame, text="More workers search artists faster but can trigger provider rate limits.", text_color=DISCONNECTED).pack(side="left", padx=8)

        ctk.CTkLabel(content, text="2 · Track filters", font=ctk.CTkFont(size=18, weight="bold"), text_color="#7bdcb5").grid(row=6, column=0, padx=12, pady=(18, 2), sticky="w")
        filters = ctk.CTkFrame(content)
        filters.grid(row=7, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkLabel(filters, text="Filters").pack(side="left", padx=14, pady=14)
        ctk.CTkCheckBox(filters, text="Skip remixes / edits", variable=self.skip_remixes, command=self._save_song_preference).pack(side="left", padx=8)
        ctk.CTkCheckBox(filters, text="Singles only", variable=self.singles_only, command=self._save_song_preference).pack(side="left", padx=8)
        ctk.CTkCheckBox(filters, text="Remove duplicate titles", variable=self.dedupe_titles, command=self._save_song_preference).pack(side="left", padx=8)

        release_frame = ctk.CTkFrame(content)
        release_frame.grid(row=8, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkLabel(release_frame, text="Release window").pack(side="left", padx=14, pady=14)
        ctk.CTkOptionMenu(release_frame, values=[
            "Any release date", "Last 30 days", "Last 90 days", "Last 365 days",
            "Last number of years", "Today through chosen date", "Custom date range",
        ], variable=self.release_window, command=self._release_window_changed).pack(side="left", padx=8)
        self.release_years_label = ctk.CTkLabel(release_frame, text="Years")
        self.release_years_entry = ctk.CTkEntry(release_frame, textvariable=self.release_years, width=70, placeholder_text="1")
        self.release_years_entry.bind("<FocusOut>", self._custom_release_dates_changed)
        self.current_date_end_label = ctk.CTkLabel(release_frame, text="End date")
        self.current_date_end_entry = ctk.CTkEntry(
            release_frame, width=105, placeholder_text="MM/DD/YYYY", placeholder_text_color="#8f98a6"
        )
        self.current_date_end_entry.bind("<FocusOut>", self._custom_release_dates_changed)
        self.custom_release_start_entry = ctk.CTkEntry(
            release_frame, width=105, placeholder_text="MM/DD/YYYY", placeholder_text_color="#8f98a6"
        )
        self.custom_range_to_label = ctk.CTkLabel(release_frame, text="to")
        self.custom_release_end_entry = ctk.CTkEntry(
            release_frame, width=105, placeholder_text="MM/DD/YYYY", placeholder_text_color="#8f98a6"
        )
        self.custom_release_start_entry.bind("<FocusOut>", self._custom_release_dates_changed)
        self.custom_release_end_entry.bind("<FocusOut>", self._custom_release_dates_changed)
        if self.custom_release_start.get():
            self.custom_release_start_entry.insert(0, self.custom_release_start.get())
        if self.custom_release_end.get():
            self.current_date_end_entry.insert(0, self.custom_release_end.get())
            self.custom_release_end_entry.insert(0, self.custom_release_end.get())
        self._refresh_release_window_controls()

        ctk.CTkLabel(content, text="3 · Playlist details", font=ctk.CTkFont(size=18, weight="bold"), text_color="#7bdcb5").grid(row=9, column=0, padx=12, pady=(18, 2), sticky="w")
        presentation = ctk.CTkFrame(content)
        presentation.grid(row=10, column=0, padx=12, pady=5, sticky="ew")
        ctk.CTkLabel(presentation, text="Playlist description").pack(side="left", padx=14, pady=14)
        ctk.CTkEntry(presentation, textvariable=self.playlist_description, width=300, placeholder_text="Optional playlist description").pack(side="left", padx=8)

        ctk.CTkLabel(content, text="4 · Streaming accounts", font=ctk.CTkFont(size=18, weight="bold"), text_color="#7bdcb5").grid(row=11, column=0, padx=12, pady=(18, 2), sticky="w")
        ctk.CTkLabel(content, text="Connect only the services you intend to use. Green means the saved session is ready.", text_color=DISCONNECTED).grid(row=12, column=0, padx=12, pady=(0, 8), sticky="w")
        services = ctk.CTkFrame(content)
        services.grid(row=13, column=0, padx=12, pady=(0, 8), sticky="ew")
        services.grid_columnconfigure(1, weight=1)
        for row, platform in enumerate(ADAPTERS):
            ctk.CTkLabel(services, text=platform, width=125, anchor="w").grid(row=row, column=0, padx=14, pady=10, sticky="w")
            label = ctk.CTkLabel(services, text="Not logged in", text_color=DISCONNECTED, anchor="w")
            label.grid(row=row, column=1, padx=8, pady=10, sticky="ew")
            self.service_status[platform] = label
            login = ctk.CTkButton(services, text="Login", width=90, command=lambda p=platform: self.login(p))
            login.grid(row=row, column=2, padx=5, pady=10)
            logout = ctk.CTkButton(services, text="Logout", width=90, fg_color="#6b3b3b", hover_color="#824646", command=lambda p=platform: self.logout(p))
            logout.grid(row=row, column=3, padx=(5, 14), pady=10)
            self.auth_buttons.append(login)

        ctk.CTkLabel(content, text="Logout removes this app's local session. Apple Music's user token remains in .env until you remove it there.", text_color=DISCONNECTED, wraplength=760, justify="left").grid(row=14, column=0, padx=12, pady=(2, 18), sticky="w")

    def _save_song_preference(self, _value: str | None = None) -> None:
        self._sync_release_date_inputs()
        self.token_store.save("preferences", {
            "include_popular": self.include_popular.get(),
            "popular_song_count": int(self.popular_song_count.get()),
            "include_recent": self.include_recent.get(),
            "recent_song_count": int(self.recent_song_count.get()),
            "artist_thread_count": int(self.artist_thread_count.get()),
            "release_window": self.release_window.get(),
            "custom_release_start": self.custom_release_start.get(),
            "custom_release_end": self.custom_release_end.get(),
            "release_years": self.release_years.get(),
            "skip_remixes": self.skip_remixes.get(), "singles_only": self.singles_only.get(),
            "dedupe_titles": self.dedupe_titles.get(),
            "library_preferences": self.library_preferences,
            "playlist_description": self.playlist_description.get(),
        })

    def _load_library_preferences(self, platform: str) -> None:
        """Load only this service's personal-library choices when it is selected."""
        if not hasattr(self, "library_liked_check"):
            return
        values = self.library_preferences.get(platform, {})
        self._loading_library_preferences = True
        self.include_library.set(values.get("enabled", False))
        self.include_liked_tracks.set(values.get("liked", False))
        self.include_playlist_tracks.set(values.get("playlists", False))
        self.include_library_collaborations.set(values.get("collaborations", True))
        self._loading_library_preferences = False
        self._refresh_library_controls()

    def _active_library_preferences(self) -> dict:
        return self.library_preferences.setdefault(self.platform.get(), {
            "enabled": False, "liked": False, "playlists": False,
            "playlist_ids": [], "playlist_names": [], "all_playlists": False,
            "collaborations": True,
        })

    def _refresh_library_controls(self) -> None:
        values = self._active_library_preferences()
        enabled = self.include_library.get()
        playlist_enabled = enabled and self.include_playlist_tracks.get()
        self.library_liked_check.configure(state="normal" if enabled else "disabled")
        self.library_playlists_check.configure(state="normal" if enabled else "disabled")
        self.choose_library_playlists_button.configure(state="normal" if playlist_enabled else "disabled")
        self.library_collaborators_check.configure(state="normal" if enabled else "disabled")
        details = (
            self.library_credits_frame, self.library_liked_check, self.library_playlists_check,
            self.choose_library_playlists_button, self.library_playlist_summary,
        )
        for widget in details:
            if enabled:
                widget.grid()
            else:
                widget.grid_remove()
        if values.get("all_playlists"):
            text = "All playlists selected"
        else:
            names = values.get("playlist_names", [])
            text = ", ".join(names) if names else "No playlists selected"
        self.library_playlist_summary.configure(text=text)

    def _library_source_changed(self) -> None:
        if self._loading_library_preferences:
            return
        self._save_library_preferences()

    def _playlist_source_changed(self) -> None:
        if self._loading_library_preferences:
            return
        self._save_library_preferences()
        if self.include_library.get() and self.include_playlist_tracks.get():
            self.choose_library_playlists()

    def _save_library_preferences(self, *_args) -> None:
        if self._loading_library_preferences:
            return
        values = self._active_library_preferences()
        values.update({
            "enabled": self.include_library.get(),
            "liked": self.include_liked_tracks.get(),
            "playlists": self.include_playlist_tracks.get(),
            "collaborations": self.include_library_collaborations.get(),
        })
        self._refresh_library_controls()
        self._save_song_preference()

    def choose_library_playlists(self) -> None:
        if self._busy:
            self._log("Wait for the current task before choosing playlists.")
            return
        platform = self.platform.get()
        values = self._active_library_preferences()

        def task() -> None:
            adapter = self._adapter(platform)
            adapter.authenticate(self._log)
            playlists = adapter.get_user_playlists()

            def show() -> None:
                def done(chosen) -> None:
                    if chosen is None:
                        return
                    values["all_playlists"] = len(chosen) == len(playlists) and bool(playlists)
                    values["playlist_ids"] = [item.id for item in chosen]
                    values["playlist_names"] = [item.name for item in chosen]
                    self._save_library_preferences()
                self._library_playlist_dialog = LibraryPlaylistDialog(
                    self, platform, playlists, set(values.get("playlist_ids", [])), done
                )
            self.after(0, show)
        self._worker(f"Loading {platform} playlists…", task)

    def _save_playlist_description(self, *_args) -> None:
        """Persist description edits without adding a noisy log entry per keystroke."""
        saved = self.token_store.load("preferences") or {}
        saved["playlist_description"] = self.playlist_description.get()
        self.token_store.save("preferences", saved)

    def _release_window_changed(self, _value: str | None = None) -> None:
        self._refresh_release_window_controls()
        self._save_song_preference()

    def _custom_release_dates_changed(self, _event=None) -> None:
        if self.release_window.get() in {"Last number of years", "Today through chosen date", "Custom date range"}:
            self._sync_release_date_inputs()
            self._save_song_preference()

    def _sync_release_date_inputs(self) -> None:
        """Keep persisted values in step with entries that intentionally use placeholders."""
        if not hasattr(self, "custom_release_start_entry"):
            return
        mode = self.release_window.get()
        if mode == "Custom date range":
            self.custom_release_start.set(self.custom_release_start_entry.get().strip())
            self.custom_release_end.set(self.custom_release_end_entry.get().strip())
        elif mode == "Today through chosen date":
            self.custom_release_end.set(self.current_date_end_entry.get().strip())

    def _refresh_release_window_controls(self) -> None:
        """Show only the input(s) needed for the selected release-date mode."""
        for widget in (
            self.release_years_label, self.release_years_entry, self.current_date_end_label, self.current_date_end_entry,
            self.custom_release_start_entry, self.custom_range_to_label, self.custom_release_end_entry,
        ):
            widget.pack_forget()
        mode = self.release_window.get()
        if mode == "Last number of years":
            self.release_years_label.pack(side="left", padx=(10, 4))
            self.release_years_entry.pack(side="left", padx=(0, 10))
        elif mode == "Today through chosen date":
            self.current_date_end_label.pack(side="left", padx=(10, 4))
            self.current_date_end_entry.pack(side="left", padx=(0, 10))
        elif mode == "Custom date range":
            self.custom_release_start_entry.pack(side="left", padx=(10, 3))
            self.custom_range_to_label.pack(side="left", padx=3)
            self.custom_release_end_entry.pack(side="left", padx=(3, 10))

    def _selected_platform_changed(self, *_args) -> None:
        self._refresh_selected_indicator()
        self._load_library_preferences(self.platform.get())

    def _refresh_selected_indicator(self) -> None:
        platform = self.platform.get()
        state = self.connection_state[platform]
        if state is True:
            text, color = f"{platform}: Logged in", CONNECTED
        elif state is None:
            text, color = f"{platform}: Checking session…", WORKING
        else:
            text, color = f"{platform}: Not logged in", DISCONNECTED
        self.selected_service_indicator.configure(text=text, text_color=color)

    def _set_service_state(self, platform: str, state: bool | None, text: str | None = None) -> None:
        """Update the Settings row and the selected-service badge together."""
        self.connection_state[platform] = state
        if state is True:
            label_text, color = text or "Logged in", CONNECTED
        elif state is None:
            label_text, color = text or "Checking saved session…", WORKING
        else:
            label_text, color = text or "Not logged in", DISCONNECTED
        self.service_status[platform].configure(text=label_text, text_color=color)
        self._refresh_selected_indicator()

    def _can_restore_session(self, platform: str) -> bool:
        """Only restore configured/saved services; never prompt a new login during startup."""
        if platform == "Apple Music":
            return bool(all([settings.apple_team_id, settings.apple_key_id, settings.apple_private_key_path,
                             settings.apple_music_user_token])) and not (self.token_store.load("apple_music") or {}).get("signed_out")
        cache_key = {"Spotify": "spotify", "SoundCloud": "soundcloud", "TIDAL": "tidal"}[platform]
        return self.token_store.load(cache_key) is not None

    def restore_saved_sessions(self) -> None:
        platforms = [platform for platform in ADAPTERS if self._can_restore_session(platform)]
        if not platforms:
            self._log("No saved service sessions to restore. Use Settings to log in.")
            return

        def task() -> None:
            for platform in platforms:
                self.after(0, lambda p=platform: self._set_service_state(p, None))
                try:
                    self._adapter(platform).authenticate(self._log)
                except Exception as error:
                    self._log(f"Could not restore {platform}: {error}")
                    self.after(0, lambda p=platform: self._set_service_state(p, False, "Session needs login"))
                else:
                    self.after(0, lambda p=platform: self._restored_service_ready(p))
        self._worker("Restoring saved streaming-service sessions…", task)

    def _restored_service_ready(self, platform: str) -> None:
        """Mark a restored session and select the first usable service at startup."""
        self._set_service_state(platform, True)
        if not self._startup_platform_selected:
            self.platform.set(platform)
            self._startup_platform_selected = True

    def _log(self, message: str) -> None:
        # Called safely from workers: widgets are only touched on the Tk main thread.
        self.after(0, lambda: self._append_log(message))

    def _append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _show_temporary_error(self, message: str) -> None:
        """Show validation feedback without forcing users to hunt through the log."""
        self._log(message)
        dialog = self._temporary_error_dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        dialog = ctk.CTkToplevel(self)
        self._temporary_error_dialog = dialog
        dialog.title("SoundFlix — Action needed")
        dialog.geometry("460x165")
        dialog.resizable(False, False)
        dialog.transient(self)
        ctk.CTkLabel(dialog, text="Action needed", font=ctk.CTkFont(size=19, weight="bold"), text_color=WORKING).pack(anchor="w", padx=20, pady=(20, 5))
        ctk.CTkLabel(dialog, text=message, wraplength=410, justify="left").pack(anchor="w", padx=20, pady=(0, 15))
        ctk.CTkButton(dialog, text="Dismiss", width=100, command=dialog.destroy).pack(anchor="e", padx=20, pady=(0, 18))
        dialog.after(10_000, lambda: dialog.destroy() if dialog.winfo_exists() else None)

    def copy_log(self) -> None:
        """Copy every line, including long tracebacks, without enabling log edits."""
        text = self.log_box.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()  # Preserve clipboard contents after focus changes.

    def clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _worker(self, label: str, task) -> None:
        if self._busy:
            self._log("A task is already running.")
            return
        self._busy = True
        self.generate_button.configure(state="disabled")
        for button in self.auth_buttons:
            button.configure(state="disabled")
        self._log(label)
        def run():
            try:
                task()
            except Exception as error:
                self._log(f"ERROR: {error}")
                self._log(traceback.format_exc(limit=2).strip())
            finally:
                self.after(0, self._finish_worker)
        threading.Thread(target=run, daemon=True).start()

    def _finish_worker(self) -> None:
        self._busy = False
        self.generate_button.configure(state="normal")
        for button in self.auth_buttons:
            button.configure(state="normal")

    def _replace_review(self, text: str) -> None:
        self.review.delete("1.0", "end"); self.review.insert("1.0", text)
        self._refresh_artist_counter()

    def _set_search_progress(self, phase: str, completed: int, total: int, active_workers: int) -> None:
        total = max(total, 1)
        self.search_progress.set(min(completed / total, 1.0))
        worker_text = f"{active_workers} active worker{'s' if active_workers != 1 else ''}"
        self.search_progress_label.configure(
            text=f"{phase} {completed} of {total} artists · {worker_text}"
        )

    def _report_search_progress(self, phase: str, completed: int, total: int, active_workers: int) -> None:
        """Accept progress from executor threads and render it on Tk's event loop."""
        self.after(0, lambda: self._set_search_progress(phase, completed, total, active_workers))

    def _refresh_artist_counter(self) -> None:
        self._artist_counter_job = None
        text = self.review.get("1.0", "end")
        count = sum(1 for line in text.splitlines() if line.strip())
        self.artist_counter.configure(text=f"Artist line{'s' if count != 1 else ''}: {count}")

    def _artist_text_changed(self, _event=None) -> None:
        """Update after Tk commits typing, paste, delete, undo, or programmatic edits."""
        self.review.edit_modified(False)
        if self._artist_counter_job is not None:
            self.after_cancel(self._artist_counter_job)
        self._artist_counter_job = self.after_idle(self._refresh_artist_counter)

    def clean_text(self) -> None:
        current = self.review.get("1.0", "end")
        self._replace_review(TextCleaner().clean_as_text(current))
        self._log("Artist text cleaned and formatted.")

    def import_artists(self) -> None:
        path = filedialog.askopenfilename(title="Import artist list", filetypes=[("Text or CSV", "*.txt *.csv"), ("All files", "*.*")])
        if not path:
            return
        with open(path, encoding="utf-8-sig") as file:
            if path.lower().endswith(".csv"):
                text = "\n".join(row[0] for row in csv.reader(file) if row)
            else:
                text = file.read()
        self._replace_review(text)
        self._log("Artist list imported. Review it, then use Clean / Format.")

    def export_artists(self) -> None:
        path = filedialog.asksaveasfilename(title="Export artist list", defaultextension=".txt", filetypes=[("Text", "*.txt"), ("CSV", "*.csv")])
        if not path:
            return
        artists = TextCleaner().clean(self.review.get("1.0", "end"))
        with open(path, "w", newline="", encoding="utf-8") as file:
            if path.lower().endswith(".csv"):
                writer = csv.writer(file); writer.writerow(["artist"]); writer.writerows([[artist] for artist in artists])
            else:
                file.write("\n".join(artists))
        self._log(f"Exported {len(artists)} artists.")

    def _adapter(self, platform: str | None = None):
        # A fresh instance keeps the adapter lifetime within one user action.
        return ADAPTERS[platform or self.platform.get()]()

    def login(self, platform: str | None = None) -> None:
        platform = platform or self.platform.get()
        def task() -> None:
            # Apple logout is local: a fresh Login explicitly re-enables its .env user token.
            if platform == "Apple Music":
                self.token_store.clear("apple_music")
            elif platform == "Spotify":
                # An explicit Login is how Spotify users grant newly requested
                # library/playlist scopes to an existing installation.
                self.token_store.clear("spotify")
            self.after(0, lambda: self._set_service_state(platform, None, "Logging in…"))
            try:
                self._adapter(platform).authenticate(self._log)
            except Exception:
                self.after(0, lambda: self._set_service_state(platform, False, "Login failed"))
                raise
            self.after(0, lambda: self._set_service_state(platform, True))
        self._worker(f"Connecting to {platform}…", task)

    def logout(self, platform: str) -> None:
        if self._busy:
            self._log("Wait for the current task before logging out.")
            return
        cache_key = {"Spotify": "spotify", "SoundCloud": "soundcloud", "TIDAL": "tidal", "Apple Music": "apple_music"}[platform]
        if platform == "Apple Music":
            # The developer/user token belongs to .env. Mark this app session logged out without editing secrets on disk.
            self.token_store.save(cache_key, {"signed_out": True})
        else:
            self.token_store.clear(cache_key)
        self._set_service_state(platform, False, "Logged out locally")
        self._log(f"{platform} local session removed.")

    def generate(self) -> None:
        artists = TextCleaner().clean(self.review.get("1.0", "end"))
        name = self.playlist_name.get().strip() or "Festival lineup"
        if not artists:
            self._log("Enter at least one artist before creating a playlist.")
            return
        library_values = self._active_library_preferences()
        include_library_tracks = self.include_library.get() and (
            self.include_liked_tracks.get() or self.include_playlist_tracks.get()
        )
        if not (self.include_popular.get() or self.include_recent.get() or include_library_tracks):
            self._log("Choose at least one song source in Settings.")
            return
        platform = self.platform.get()
        release_days = {"Any release date": 0, "Last 30 days": 30, "Last 90 days": 90, "Last 365 days": 365}.get(self.release_window.get(), 0)
        release_start = release_end = None
        if self.release_window.get() == "Last number of years":
            try:
                years = int(self.release_years.get())
                if years < 1:
                    raise ValueError
                release_end = date.today()
                try:
                    release_start = release_end.replace(year=release_end.year - years)
                except ValueError:  # February 29th in a non-leap target year.
                    release_start = release_end.replace(year=release_end.year - years, day=28)
            except ValueError:
                self._show_temporary_error("Enter a whole number of years greater than zero in Settings.")
                return
        elif self.release_window.get() == "Today through chosen date":
            if not self.current_date_end_entry.get().strip():
                self._show_temporary_error("Select an end date in Settings before building the playlist.")
                return
            try:
                release_start = date.today()
                release_end = self._parse_custom_date(self.current_date_end_entry.get())
            except ValueError:
                self._show_temporary_error("Enter the chosen end date as MM/DD/YYYY in Settings.")
                return
            if release_end < release_start:
                self._show_temporary_error("The chosen date must be today or later.")
                return
        elif self.release_window.get() == "Custom date range":
            if not self.custom_release_start_entry.get().strip() or not self.custom_release_end_entry.get().strip():
                self._show_temporary_error("Select both dates in Settings before building the playlist.")
                return
            try:
                release_start = self._parse_custom_date(self.custom_release_start_entry.get())
                release_end = self._parse_custom_date(self.custom_release_end_entry.get())
            except ValueError:
                self._show_temporary_error("Enter both custom dates as MM/DD/YYYY in Settings.")
                return
            if release_start > release_end:
                self._show_temporary_error("The custom release range start date must be before its end date.")
                return
        options = PlaylistOptions(
            include_popular=self.include_popular.get(), popular_song_count=int(self.popular_song_count.get()),
            include_recent=self.include_recent.get(), recent_song_count=int(self.recent_song_count.get()),
            skip_remixes=self.skip_remixes.get(), singles_only=self.singles_only.get(),
            released_within_days=release_days, release_start=release_start, release_end=release_end,
            dedupe_titles=self.dedupe_titles.get(),
            include_liked_tracks=include_library_tracks and self.include_liked_tracks.get(),
            include_playlist_tracks=include_library_tracks and self.include_playlist_tracks.get(),
            selected_playlist_ids=tuple(library_values.get("playlist_ids", [])),
            all_library_playlists=bool(library_values.get("all_playlists", False)),
            include_collaborations=self.include_library_collaborations.get(),
        )
        if release_start or release_end:
            self._log(f"Release filter: {release_start or 'any date'} through {release_end or 'today'}.")
        elif release_days:
            self._log(f"Release filter: last {release_days} days through today.")
        worker_count = int(self.artist_thread_count.get())
        self._set_search_progress("Searching", 0, len(artists), 0)
        def task():
            adapter = self._adapter()
            try:
                adapter.authenticate(self._log)  # Restore/refresh a token or use active TIDAL session.
            except Exception:
                self.after(0, lambda: self._set_service_state(platform, False, "Login required"))
                raise
            self.after(0, lambda: self._set_service_state(platform, True))
            builder = PlaylistBuilder(
                adapter,
                self._log,
                adapter_factory=lambda: self._adapter(platform),
                worker_count=worker_count,
                progress=lambda phase, completed, total, active_workers: self._report_search_progress(
                    phase, completed, total, active_workers
                ),
            )
            selected: dict = {}
            selection_ready = threading.Event()
            selection_cancelled = [False]

            def confirmed(choices: dict) -> None:
                selected.update(choices)
                selection_ready.set()

            def cancelled() -> None:
                selection_cancelled[0] = True
                selection_ready.set()

            def discovered(match) -> None:
                def show() -> None:
                    if selection_cancelled[0]:
                        return
                    if self._artist_match_dialog is None or not self._artist_match_dialog.winfo_exists():
                        self._artist_match_dialog = ArtistMatchDialog(
                            self, [match], confirmed, cancelled, add_custom_profile,
                        )
                    else:
                        self._artist_match_dialog.add_match(match)
                self.after(0, show)

            def add_custom_profile(_requested_name: str, url: str, completed) -> None:
                """Resolve a pasted provider link without interrupting the catalog scan."""
                def task() -> None:
                    try:
                        custom_adapter = self._adapter(platform)
                        custom_adapter.authenticate(self._log)
                        artist = custom_adapter.artist_from_profile_url(url)
                        if not artist:
                            raise RuntimeError("No artist profile was found at that link.")
                        candidate = PlaylistBuilder(custom_adapter, self._log).candidate_preview(artist)
                        if not candidate:
                            raise RuntimeError("That artist has no playable top-song preview.")
                    except Exception as error:
                        self.after(0, lambda: completed(None, str(error)))
                    else:
                        self.after(0, lambda: completed(candidate, None))
                threading.Thread(target=task, daemon=True).start()

            ambiguous, resolved = builder.find_ambiguous_artists(artists, discovered)
            if ambiguous:
                def finish_discovery() -> None:
                    dialog = self._artist_match_dialog
                    if dialog is not None and dialog.winfo_exists():
                        dialog.mark_search_complete()
                self.after(0, finish_discovery)
                selection_ready.wait()
                self._artist_match_dialog = None
                if selection_cancelled[0]:
                    raise RuntimeError("Artist selection was cancelled.")
                resolved.update(selected)
            self._show_playlist_review(builder.collect(artists, options, resolved), platform, name)
        self._worker(f"Checking artist profiles for {len(artists)} artist(s)…", task)

    @staticmethod
    def _parse_custom_date(value: str):
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()

    def _show_playlist_review(self, preview, platform: str, name: str) -> None:
        self.after(0, lambda: self._set_search_progress(
            "Ready", len(preview.artists), len(preview.artists), 0
        ))
        self.after(0, lambda: PlaylistReviewDialog(
            self, preview, lambda tracks, artists: self.create_approved(platform, name, tracks, artists)
        ))
        self._log(f"Review ready: {len(preview.tracks)} candidate tracks. No playlist has been created yet.")

    def create_approved(self, platform: str, name: str, tracks, artists: list[str]) -> None:
        description = self.playlist_description.get().strip()
        def task():
            adapter = self._adapter(platform)
            adapter.authenticate(self._log)
            result = PlaylistBuilder(adapter, self._log).create(name, tracks, description)
            history = self.token_store.load("playlist_history") or []
            history.insert(0, {
                "name": result.name, "platform": platform, "tracks": result.track_count,
                "url": result.url or "", "artists": artists,
            })
            self.token_store.save("playlist_history", history[:50])
            self.after(0, self.refresh_history)
            url = f" Open it: {result.url}" if result.url else ""
            self._log(f"Done — created '{result.name}' with {result.track_count} tracks.{url}")
        self._worker(f"Creating approved {platform} playlist…", task)
