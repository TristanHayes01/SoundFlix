"""Playlist selector used by the optional personal-library source."""
from __future__ import annotations
import customtkinter as ctk
from app.models import UserPlaylist


class LibraryPlaylistDialog(ctk.CTkToplevel):
    def __init__(self, parent, platform: str, playlists: list[UserPlaylist], selected_ids: set[str], on_done) -> None:
        super().__init__(parent)
        self.title(f"SoundFlix — Select {platform} playlists")
        self.geometry("620x620")
        self.minsize(480, 420)
        self.transient(parent)
        self.on_done = on_done
        self.playlists = playlists
        self.variables = {item.id: ctk.BooleanVar(value=item.id in selected_ids) for item in playlists}
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        ctk.CTkLabel(self, text="Choose playlists to scan", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=18, pady=(18, 3))
        ctk.CTkLabel(self, text="Songs matching your supplied artist list will be added for review.", text_color="#a7adb8").pack(anchor="w", padx=18, pady=(0, 12))
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkButton(controls, text="Select all", width=105, command=lambda: self._set_all(True)).pack(side="left")
        ctk.CTkButton(controls, text="Deselect all", width=115, command=lambda: self._set_all(False)).pack(side="left", padx=8)
        self.listing = ctk.CTkScrollableFrame(self)
        self.listing.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        if playlists:
            for item in playlists:
                ctk.CTkCheckBox(self.listing, text=item.name, variable=self.variables[item.id]).pack(anchor="w", padx=10, pady=7)
        else:
            ctk.CTkLabel(self.listing, text="No accessible playlists were found.").pack(padx=10, pady=12)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 18))
        ctk.CTkButton(actions, text="Cancel", command=self._cancel).pack(side="right")
        ctk.CTkButton(actions, text="Use selected playlists", command=self._confirm).pack(side="right", padx=8)

    def _set_all(self, value: bool) -> None:
        for variable in self.variables.values():
            variable.set(value)

    def _confirm(self) -> None:
        self.on_done([item for item in self.playlists if self.variables[item.id].get()])
        self.destroy()

    def _cancel(self) -> None:
        self.on_done(None)
        self.destroy()
