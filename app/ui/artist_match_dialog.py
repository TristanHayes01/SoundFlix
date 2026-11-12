"""Confirmation UI for artists whose catalog search returns duplicate names."""
from __future__ import annotations
from io import BytesIO
import threading
import webbrowser
import customtkinter as ctk
from PIL import Image
import requests
from app.models import Artist
from app.services.playlist_builder import AmbiguousArtist, ArtistCandidate


class ArtistMatchDialog(ctk.CTkToplevel):
    SKIP_VALUE = "__skip_artist__"

    def __init__(self, parent, matches: list[AmbiguousArtist], on_confirm, on_cancel=None,
                 on_custom_profile=None) -> None:
        super().__init__(parent)
        self.title("SoundFlix — Confirm artists")
        self.geometry("820x680")
        self.minsize(620, 460)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.matches, self.on_confirm, self.on_cancel = [], on_confirm, on_cancel
        self.on_custom_profile = on_custom_profile
        self.index = 0
        self.search_complete = False
        self.custom_lookups = 0
        self.selected: dict[str, ctk.StringVar] = {}
        self.artists_by_key: dict[tuple[str, str], Artist] = {}
        self.profile_images: list[ctk.CTkImage] = []

        ctk.CTkLabel(self, text="Choose the correct artist profile", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=18, pady=(18, 4))
        self.notice = ctk.CTkLabel(self, text="More duplicate-name matches may appear while SoundFlix continues searching.", text_color="#e5a93d", wraplength=760, justify="left")
        self.notice.pack(anchor="w", padx=18, pady=(0, 10))
        self.progress = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.progress.pack(anchor="w", padx=18, pady=(0, 2))
        self.listing = ctk.CTkScrollableFrame(self)
        self.listing.pack(fill="both", expand=True, padx=18, pady=8)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=18, pady=(4, 18))
        ctk.CTkButton(controls, text="Cancel", command=self.cancel).pack(side="right", padx=(8, 0))
        self.confirm_button = ctk.CTkButton(controls, text="Searching for matches…", command=self.confirm, state="disabled")
        self.confirm_button.pack(side="right")
        self.previous_button = ctk.CTkButton(controls, text="Previous artist", command=self.previous_match)
        self.previous_button.pack(side="left")
        self.next_button = ctk.CTkButton(controls, text="Next artist", command=self.next_match)
        self.next_button.pack(side="left", padx=(8, 0))
        for match in matches:
            self.add_match(match)

    def add_match(self, match: AmbiguousArtist) -> None:
        """Append a newly discovered duplicate-name match without interrupting scanning."""
        requested = match.requested_name.casefold()
        self.matches.append(match)
        self.selected[requested] = ctk.StringVar(value=match.candidates[0].artist.id)
        for candidate in match.candidates:
            self.artists_by_key[(requested, candidate.artist.id)] = candidate.artist
        if len(self.matches) == 1:
            self._render_match()
        else:
            self._refresh_navigation()

    def mark_search_complete(self) -> None:
        self.search_complete = True
        self.notice.configure(text="All duplicate-name matches are ready. Confirm your selections to continue.")
        self._update_confirm_button()

    def _render_match(self) -> None:
        """Render one ambiguous name at a time to avoid a misleading empty tail."""
        for child in self.listing.winfo_children():
            child.destroy()
        self.listing._parent_canvas.yview_moveto(0)
        match = self.matches[self.index]
        requested = match.requested_name.casefold()
        self.progress.configure(text=f"Artist {self.index + 1} of {len(self.matches)} · {match.requested_name} ({len(match.candidates)} profiles found)")
        if self.on_custom_profile:
            custom = ctk.CTkFrame(self.listing, fg_color="transparent")
            custom.pack(fill="x", padx=8, pady=(6, 4))
            ctk.CTkLabel(custom, text="Know the correct profile? Paste its link:").pack(side="left", padx=(0, 8))
            self.custom_url = ctk.CTkEntry(custom, placeholder_text="Artist profile URL")
            self.custom_url.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.custom_status = ctk.CTkLabel(self.listing, text="", text_color="#e5a93d")
            ctk.CTkButton(custom, text="Add profile", width=105, command=lambda item=match: self._add_custom_profile(item)).pack(side="right")
        ctk.CTkRadioButton(
            self.listing,
            text="None of these profiles — skip this artist",
            variable=self.selected[requested],
            value=self.SKIP_VALUE,
            text_color="#e5a93d",
        ).pack(anchor="w", padx=18, pady=(8, 4))
        for candidate in match.candidates:
            artist = candidate.artist
            row = ctk.CTkFrame(self.listing)
            row.pack(fill="x", padx=8, pady=6)
            avatar = ctk.CTkLabel(row, text="No image", width=76, height=76, corner_radius=8, fg_color="#303846", text_color="#a7adb8")
            avatar.pack(side="left", padx=(12, 8), pady=10)
            details = ctk.CTkFrame(row, fg_color="transparent")
            details.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=6)
            ctk.CTkRadioButton(details, text=artist.name, variable=self.selected[requested], value=artist.id).pack(anchor="w", pady=(2, 2))
            songs = " • ".join(track.title for track in candidate.sample_tracks) or "No top-song preview available"
            ctk.CTkLabel(details, text=f"Top 5 songs: {songs}", wraplength=560, justify="left", text_color="#a7adb8").pack(anchor="w", pady=(0, 6))
            collaborators = " • ".join(candidate.collaborators) or "No collaborator credits found in available catalog tracks"
            ctk.CTkLabel(details, text=f"Collaborators across catalog: {collaborators}", wraplength=560, justify="left", text_color="#7bdcb5").pack(anchor="w", pady=(0, 6))
            if artist.profile_url:
                ctk.CTkButton(details, text="Open profile", width=110, command=lambda url=artist.profile_url: webbrowser.open(url)).pack(anchor="w", pady=(0, 4))
            if artist.profile_image_url:
                self._load_profile_image(avatar, artist.profile_image_url)
        self._refresh_navigation()

    def _add_custom_profile(self, match: AmbiguousArtist) -> None:
        url = self.custom_url.get().strip()
        if not url:
            self.custom_status.configure(text="Paste an artist profile link first.")
            return
        self.custom_lookups += 1
        status = self.custom_status
        status.configure(text="Checking pasted profile…")
        self._update_confirm_button()

        def finished(candidate: ArtistCandidate | None, error: str | None = None) -> None:
            self.custom_lookups -= 1
            if not self.winfo_exists():
                return
            if candidate:
                self.add_custom_candidate(match.requested_name, candidate)
                if status.winfo_exists():
                    status.configure(text=f"Added {candidate.artist.name}. Select it above.", text_color="#7bdcb5")
            else:
                if status.winfo_exists():
                    status.configure(text=error or "That profile could not be added.")
            self._update_confirm_button()

        self.on_custom_profile(match.requested_name, url, finished)

    def add_custom_candidate(self, requested_name: str, candidate: ArtistCandidate) -> None:
        """Insert a manually linked profile and select it for the requested artist."""
        requested = requested_name.casefold()
        for match_index, match in enumerate(self.matches):
            if match.requested_name.casefold() != requested:
                continue
            if candidate.artist.id not in {item.artist.id for item in match.candidates}:
                match.candidates.append(candidate)
            self.artists_by_key[(requested, candidate.artist.id)] = candidate.artist
            self.selected[requested].set(candidate.artist.id)
            if match_index == self.index:
                self._render_match()
            return

    def _update_confirm_button(self) -> None:
        ready = self.search_complete and self.custom_lookups == 0
        self.confirm_button.configure(
            text="Use selected artists" if ready else "Searching for matches…",
            state="normal" if ready else "disabled",
        )

    def _refresh_navigation(self) -> None:
        self.progress.configure(text=f"Artist {self.index + 1} of {len(self.matches)} · {self.matches[self.index].requested_name} ({len(self.matches[self.index].candidates)} profiles found)")
        self.previous_button.configure(state="normal" if self.index else "disabled")
        self.next_button.configure(state="normal" if self.index < len(self.matches) - 1 else "disabled")

    def next_match(self) -> None:
        if self.index < len(self.matches) - 1:
            self.index += 1
            self._render_match()

    def previous_match(self) -> None:
        if self.index:
            self.index -= 1
            self._render_match()

    def _load_profile_image(self, label: ctk.CTkLabel, url: str) -> None:
        """Fetch thumbnails off the GUI thread; a missing image is non-fatal."""
        def task() -> None:
            try:
                response = requests.get(url, timeout=10, headers={"User-Agent": "SoundFlix/1.0"})
                response.raise_for_status()
                image = Image.open(BytesIO(response.content)).convert("RGB")
                image.thumbnail((76, 76))
            except Exception:
                return

            def show() -> None:
                if not label.winfo_exists():
                    return
                thumbnail = ctk.CTkImage(light_image=image, dark_image=image, size=(76, 76))
                self.profile_images.append(thumbnail)
                label.configure(image=thumbnail, text="")
            self.after(0, show)
        threading.Thread(target=task, daemon=True).start()

    def confirm(self) -> None:
        choices = {
            requested: None if variable.get() == self.SKIP_VALUE else self.artists_by_key[(requested, variable.get())]
            for requested, variable in self.selected.items()
        }
        self.on_confirm(choices)
        self.destroy()

    def cancel(self) -> None:
        if self.on_cancel:
            self.on_cancel()
        self.destroy()
