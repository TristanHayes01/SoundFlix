"""Interactive crop dialog built on Tk's Canvas (CustomTkinter has no native crop widget)."""
from __future__ import annotations
import tkinter as tk
from PIL import Image, ImageTk


class CropDialog(tk.Toplevel):
    """Drag a rectangle over the displayed image; callback receives the full-resolution crop."""

    MAX_SIZE = (1050, 700)

    def __init__(self, parent, source: Image.Image, on_accept) -> None:
        super().__init__(parent)
        self.title("Crop flyer — drag to select text")
        self.transient(parent); self.grab_set()
        self.source, self.on_accept = source.copy(), on_accept
        self.start_source = self.source_box = None
        self.scale, self.offset = 1.0, (0, 0)
        self.minsize(440, 330)
        self.geometry(f"{min(self.MAX_SIZE[0] + 24, source.width + 24)}x{min(self.MAX_SIZE[1] + 78, source.height + 78)}")
        # Both the dialog and Canvas expand. The preview is redrawn at the available size.
        self.resizable(True, True)
        self.canvas = tk.Canvas(self, cursor="crosshair", highlightthickness=0, background="#1f1f1f")
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)
        self.canvas.bind("<Configure>", self._redraw)
        controls = tk.Frame(self); controls.pack(fill="x", padx=12, pady=(4, 12))
        tk.Label(controls, text="Drag across the names to OCR.").pack(side="left")
        tk.Button(controls, text="Use crop", command=self._accept).pack(side="right")
        tk.Button(controls, text="Cancel", command=self.destroy).pack(side="right", padx=6)

    def _source_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def _canvas_to_source(self, x: float, y: float) -> tuple[int, int]:
        x = min(max(x - self.offset[0], 0), self.preview.width) / self.scale
        y = min(max(y - self.offset[1], 0), self.preview.height) / self.scale
        return int(x), int(y)

    def _redraw(self, _event=None) -> None:
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 2 or height < 2:
            return
        self.scale = min(width / self.source.width, height / self.source.height)
        size = (max(1, int(self.source.width * self.scale)), max(1, int(self.source.height * self.scale)))
        self.preview = self.source.resize(size)
        self.tk_image = ImageTk.PhotoImage(self.preview)
        self.offset = ((width - size[0]) // 2, (height - size[1]) // 2)
        self.canvas.delete("all")
        self.canvas.create_image(*self.offset, image=self.tk_image, anchor="nw")
        if self.source_box:
            x1, y1, x2, y2 = self.source_box
            self.canvas.create_rectangle(*self._source_to_canvas(x1, y1), *self._source_to_canvas(x2, y2), outline="#35a2ff", width=3)

    def _start(self, event) -> None:
        self.start_source = self._canvas_to_source(event.x, event.y)
        self.source_box = (*self.start_source, *self.start_source)
        self._redraw()

    def _drag(self, event) -> None:
        if self.start_source:
            self.source_box = (*self.start_source, *self._canvas_to_source(event.x, event.y))
            self._redraw()

    def _finish(self, event) -> None:
        if self.start_source:
            self.source_box = (*self.start_source, *self._canvas_to_source(event.x, event.y))
            self._redraw()

    def _accept(self) -> None:
        if not self.source_box:
            return
        x1, y1, x2, y2 = self.source_box
        left, right = sorted((max(0, x1), min(self.source.width, x2)))
        top, bottom = sorted((max(0, y1), min(self.source.height, y2)))
        if right - left < 5 or bottom - top < 5:
            return
        self.on_accept(self.source.crop((left, top, right, bottom)))
        self.destroy()
