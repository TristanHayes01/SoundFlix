"""Modern CustomTkinter UI. All slow work runs in daemon workers and reports via after()."""
from __future__ import annotations
import threading
import traceback
from pathlib import Path
import tkinter.filedialog as filedialog
import customtkinter as ctk
from PIL import Image, ImageOps

from app.adapters import ADAPTERS
from app.config import settings
from app.ocr.engines import BuiltInOCREngine, TesseractEngine
from app.services.playlist_builder import PlaylistBuilder
from app.services.text_cleaner import TextCleaner
from app.services.token_store import TokenStore
from .crop_dialog import CropDialog

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

CONNECTED = "#2fa572"
DISCONNECTED = "#a7adb8"
WORKING = "#e5a93d"
FAILED = "#d65a5a"


class FlyerPlaylistApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SoundFlix")
        self.geometry("1120x760")
        self.minsize(900, 650)
        self.current_image: Image.Image | None = None
        self._busy = False
        self.token_store = TokenStore()
        saved = self.token_store.load("preferences") or {}
        self.top_song_count = ctk.StringVar(value=str(saved.get("songs_per_artist", 5)))
        self.auth_buttons: list[ctk.CTkButton] = []
        self.service_status: dict[str, ctk.CTkLabel] = {}
        self.connection_state: dict[str, bool | None] = {name: False for name in ADAPTERS}
        self._build()
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
        self.ocr_option = ctk.StringVar(value="Built-in OCR (EasyOCR)")
        ctk.CTkOptionMenu(top, values=["Built-in OCR (EasyOCR)", "Tesseract OCR (system install)"], variable=self.ocr_option).grid(row=0, column=2, padx=8)
        self.generate_button = ctk.CTkButton(top, text="Create playlist", command=self.generate); self.generate_button.grid(row=0, column=3, padx=8)
        self.selected_service_indicator = ctk.CTkLabel(top, text="Spotify: Not logged in", text_color=DISCONNECTED)
        self.selected_service_indicator.grid(row=0, column=4, padx=8)
        self.platform.trace_add("write", self._selected_platform_changed)

        tabs = ctk.CTkTabview(self); tabs.grid(row=1, column=0, padx=14, pady=8, sticky="nsew")
        builder_tab = tabs.add("Playlist builder")
        settings_tab = tabs.add("Settings")
        builder_tab.grid_columnconfigure((0, 1), weight=1, uniform="columns")
        builder_tab.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(builder_tab); left.grid(row=0, column=0, padx=(0, 7), pady=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(left, text="1. Add artist names or read a flyer", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=14, pady=(14, 8), sticky="w")
        buttons = ctk.CTkFrame(left, fg_color="transparent"); buttons.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkButton(buttons, text="Upload flyer", command=self.upload_image).pack(side="left")
        self.crop_button = ctk.CTkButton(buttons, text="Crop text area", command=self.crop_image, state="disabled"); self.crop_button.pack(side="left", padx=8)
        ctk.CTkButton(buttons, text="Run OCR", command=self.run_ocr).pack(side="left")
        self.ocr_status = ctk.CTkLabel(left, text="OCR can be unreliable — review every artist before creating a playlist.", text_color=WORKING, wraplength=460, justify="left")
        self.ocr_status.grid(row=2, column=0, padx=14, pady=(0, 2), sticky="w")
        self.review = ctk.CTkTextbox(left, wrap="word"); self.review.grid(row=3, column=0, padx=14, pady=8, sticky="nsew")
        footer = ctk.CTkFrame(left, fg_color="transparent"); footer.grid(row=4, column=0, padx=14, pady=(0, 14), sticky="ew")
        ctk.CTkButton(footer, text="Clean / Format", command=self.clean_text).pack(side="left")
        ctk.CTkLabel(footer, text="One artist per line. You can edit freely.").pack(side="left", padx=10)

        right = ctk.CTkFrame(builder_tab); right.grid(row=0, column=1, padx=(7, 0), pady=0, sticky="nsew")
        right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(right, text="2. Playlist details and activity", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=14, pady=(14, 8), sticky="w")
        self.playlist_name = ctk.CTkEntry(right, placeholder_text="Playlist name (for example: Lost Lands lineup)"); self.playlist_name.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        self.log_box = ctk.CTkTextbox(right, state="disabled", wrap="word"); self.log_box.grid(row=2, column=0, padx=14, pady=8, sticky="nsew")
        log_controls = ctk.CTkFrame(right, fg_color="transparent"); log_controls.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="ew")
        ctk.CTkButton(log_controls, text="Copy log", width=100, command=self.copy_log).pack(side="left")
        ctk.CTkButton(log_controls, text="Clear log", width=100, command=self.clear_log).pack(side="left", padx=8)
        self.status = ctk.CTkLabel(log_controls, text="Ready"); self.status.pack(side="left", padx=6)
        self._build_settings(settings_tab)

    def _build_settings(self, parent) -> None:
        """Account controls are intentionally separate from the playlist-building workflow."""
        parent.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(parent, text="Settings", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")
        count_frame = ctk.CTkFrame(parent)
        count_frame.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        ctk.CTkLabel(count_frame, text="Songs to add per artist").pack(side="left", padx=14, pady=14)
        ctk.CTkOptionMenu(count_frame, values=[str(n) for n in range(1, 11)], variable=self.top_song_count, command=self._save_song_preference).pack(side="left", padx=8)
        ctk.CTkLabel(count_frame, text="Spotify catalog search currently returns up to 10 ranked matches.").pack(side="left", padx=8)

        ctk.CTkLabel(parent, text="Streaming services", font=ctk.CTkFont(size=17, weight="bold")).grid(row=2, column=0, padx=20, pady=(18, 4), sticky="w")
        services = ctk.CTkFrame(parent)
        services.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="ew")
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

        ctk.CTkLabel(parent, text="Logout removes this app's local session. Apple Music's user token remains in .env until you remove it there.", wraplength=760, justify="left").grid(row=4, column=0, padx=20, pady=(0, 20), sticky="w")

    def _save_song_preference(self, _value: str | None = None) -> None:
        self.token_store.save("preferences", {"songs_per_artist": int(self.top_song_count.get())})
        self._log(f"Will add up to {self.top_song_count.get()} song(s) per artist.")

    def _selected_platform_changed(self, *_args) -> None:
        self._refresh_selected_indicator()

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
                    self.after(0, lambda p=platform: self._set_service_state(p, True))
        self._worker("Restoring saved streaming-service sessions…", task)

    def _log(self, message: str) -> None:
        # Called safely from workers: widgets are only touched on the Tk main thread.
        self.after(0, lambda: self._append_log(message))

    def _append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.status.configure(text=message)

    def copy_log(self) -> None:
        """Copy every line, including long tracebacks, without enabling log edits."""
        text = self.log_box.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()  # Preserve clipboard contents after focus changes.
        self.status.configure(text="Complete log copied to clipboard.")

    def clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.status.configure(text="Log cleared.")

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

    def upload_image(self) -> None:
        filename = filedialog.askopenfilename(title="Choose a festival flyer", filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        if filename:
            self.current_image = ImageOps.exif_transpose(Image.open(Path(filename))).convert("RGB")
            self.crop_button.configure(state="normal")
            self._log(f"Loaded image: {Path(filename).name}. Crop it or run OCR on the full image.")

    def crop_image(self) -> None:
        if self.current_image:
            CropDialog(self, self.current_image, self._set_crop)

    def _set_crop(self, crop: Image.Image) -> None:
        self.current_image = crop
        self._log("Crop selected. Press Run OCR to extract its text.")

    def run_ocr(self) -> None:
        if not self.current_image:
            self._log("Upload an image before running OCR.")
            return
        image = self.current_image.copy()
        engine = TesseractEngine() if self.ocr_option.get().startswith("Tesseract") else BuiltInOCREngine()
        def task():
            try:
                text = engine.extract_text(image)
            except Exception:
                self.after(0, lambda: self.ocr_status.configure(text="OCR did not finish. Check the log or choose another OCR engine.", text_color=FAILED))
                raise
            self.after(0, lambda: self._replace_review(text))
            self.after(0, lambda: self.ocr_status.configure(text="OCR complete. Review every artist name before creating a playlist.", text_color=WORKING))
            self._log("OCR complete. Review the editable text, then Clean / Format.")
        self.ocr_status.configure(text=f"{engine.label} is running…", text_color=WORKING)
        self._worker(f"Running {engine.label}…", task)

    def _replace_review(self, text: str) -> None:
        self.review.delete("1.0", "end"); self.review.insert("1.0", text)

    def clean_text(self) -> None:
        current = self.review.get("1.0", "end")
        self._replace_review(TextCleaner().clean_as_text(current))
        self._log("Artist text cleaned and formatted.")

    def _adapter(self, platform: str | None = None):
        # A fresh instance keeps the adapter lifetime within one user action.
        return ADAPTERS[platform or self.platform.get()]()

    def login(self, platform: str | None = None) -> None:
        platform = platform or self.platform.get()
        def task() -> None:
            # Apple logout is local: a fresh Login explicitly re-enables its .env user token.
            if platform == "Apple Music":
                self.token_store.clear("apple_music")
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
        platform = self.platform.get()
        songs_per_artist = int(self.top_song_count.get())
        def task():
            adapter = self._adapter()
            try:
                adapter.authenticate(self._log)  # Restore/refresh a token or use active TIDAL session.
            except Exception:
                self.after(0, lambda: self._set_service_state(platform, False, "Login required"))
                raise
            self.after(0, lambda: self._set_service_state(platform, True))
            result = PlaylistBuilder(adapter, self._log).build(artists, name, songs_per_artist)
            url = f" Open it: {result.url}" if result.url else ""
            self._log(f"Done — created '{result.name}' with {result.track_count} tracks.{url}")
        self._worker(f"Creating {platform} playlist from {len(artists)} artist(s), up to {songs_per_artist} each…", task)
