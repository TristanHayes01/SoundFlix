"""Approval dialog for matched artists and individual tracks before account mutation."""
from __future__ import annotations
import csv
from io import BytesIO
import threading
import tkinter.filedialog as filedialog
import customtkinter as ctk
from PIL import Image
import requests
from app.models import Track
from app.services.playlist_builder import PlaylistPreview


class PlaylistReviewDialog(ctk.CTkToplevel):
    def __init__(self, parent, preview: PlaylistPreview, on_create) -> None:
        super().__init__(parent)
        self.title("SoundFlix — Review matches")
        self.geometry("760x650")
        self.minsize(600, 450)
        self.transient(parent)
        self.preview, self.on_create = preview, on_create
        self.selected: list[tuple[Track, ctk.BooleanVar]] = []
        self.images: list[ctk.CTkImage] = []
        ctk.CTkLabel(self, text="Review matches before creating the playlist", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(self, text="Unchecked tracks will not be added. A matched artist name is shown above its tracks.", text_color="#e5a93d").pack(anchor="w", padx=18, pady=(0, 10))
        self.listing = ctk.CTkScrollableFrame(self)
        self.listing.pack(fill="both", expand=True, padx=18, pady=8)
        for entry in preview.artists:
            heading = entry.matched_name or entry.requested_name
            suffix = f" — {entry.note}" if entry.note else ""
            artist_controls = ctk.CTkFrame(self.listing)
            artist_controls.pack(fill="x", pady=(10, 2))
            artist_image = ctk.CTkLabel(artist_controls, text="Artist", width=54, height=54, corner_radius=8, fg_color="#303846", text_color="#a7adb8")
            artist_image.pack(side="left", padx=(8, 10), pady=8)
            ctk.CTkLabel(artist_controls, text=heading + suffix, font=ctk.CTkFont(weight="bold"), anchor="w").pack(side="left", fill="x", expand=True)
            artist_selected: list[tuple[ctk.BooleanVar, ctk.CTkButton, str]] = []
            ctk.CTkButton(artist_controls, text="Select all", width=82, command=lambda rows=artist_selected: self._set_artist_selection(rows, True)).pack(side="right")
            ctk.CTkButton(artist_controls, text="Deselect all", width=94, command=lambda rows=artist_selected: self._set_artist_selection(rows, False)).pack(side="right", padx=6)
            if entry.profile_image_url:
                self._load_image(artist_image, entry.profile_image_url, 54)
            for track in entry.tracks:
                checked = ctk.BooleanVar(value=True)
                label = f"{track.title} — {track.artist_name}"
                if track.release_date and track.selection_source != "recent":
                    label += f"  ({track.release_date[:10]})"
                track_row = ctk.CTkFrame(self.listing, fg_color="#252b35")
                track_row.pack(fill="x", padx=14, pady=3)
                track_row.grid_columnconfigure(0, weight=1)
                track_button = ctk.CTkButton(
                    track_row,
                    text=f"✓  {label}",
                    anchor="w",
                    fg_color="#303846",
                    hover_color="#3b4655",
                    command=lambda value=checked, button=None, text=label: None,
                )
                track_button.configure(command=lambda value=checked, button=track_button, text=label: self._toggle_track(value, button, text))
                track_button.grid(row=0, column=0, padx=10, pady=8, sticky="ew")
                self.selected.append((track, checked))
                artist_selected.append((checked, track_button, label))
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=18, pady=(4, 18))
        ctk.CTkButton(controls, text="Export selected CSV", command=self.export_csv).pack(side="left")
        ctk.CTkButton(controls, text="Create approved playlist", command=self.approve).pack(side="right")
        ctk.CTkButton(controls, text="Cancel", command=self.destroy).pack(side="right", padx=8)

    def tracks(self) -> list[Track]:
        return [track for track, checked in self.selected if checked.get()]

    @staticmethod
    def _set_artist_selection(rows: list[tuple[ctk.BooleanVar, ctk.CTkButton, str]], selected: bool) -> None:
        for value, button, label in rows:
            value.set(selected)
            button.configure(text=f"{'✓' if selected else '○'}  {label}")

    @staticmethod
    def _toggle_track(value: ctk.BooleanVar, button: ctk.CTkButton, label: str) -> None:
        selected = not value.get()
        value.set(selected)
        button.configure(text=f"{'✓' if selected else '○'}  {label}")

    def _load_image(self, label: ctk.CTkLabel, url: str, size: int) -> None:
        """Fetch provider artwork off the GUI thread; unavailable art remains a placeholder."""
        def task() -> None:
            try:
                response = requests.get(url, timeout=10, headers={"User-Agent": "SoundFlix/1.0"})
                response.raise_for_status()
                image = Image.open(BytesIO(response.content)).convert("RGB")
                image.thumbnail((size, size))
            except Exception:
                return

            def show() -> None:
                if not label.winfo_exists():
                    return
                thumbnail = ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
                self.images.append(thumbnail)
                label.configure(image=thumbnail, text="")
            self.after(0, show)
        threading.Thread(target=task, daemon=True).start()

    def export_csv(self) -> None:
        destination = filedialog.asksaveasfilename(parent=self, title="Export selected tracks", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not destination:
            return
        with open(destination, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["title", "artist", "release_date", "platform_id"])
            writer.writerows((track.title, track.artist_name, track.release_date or "", track.id) for track in self.tracks())

    def approve(self) -> None:
        tracks = self.tracks()
        if tracks:
            self.on_create(tracks)
            self.destroy()
