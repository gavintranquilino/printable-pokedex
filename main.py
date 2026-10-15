"""Create a one-page alphabetical Pokémon list from an editable CSV."""

import csv
import io
import math
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from tkinter import Canvas, Tk, StringVar, filedialog, messagebox, ttk

from PIL import Image, ImageTk

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


DATA_FILE = Path(__file__).with_name("pokemon_species.csv")
DEFAULT_INPUT = Path(__file__).with_name("missing_pokemon.csv")
PAGES = {"US Letter": letter, "A4": A4}
MARGIN = 18
TITLE_SPACE = 42
FOOTER_SPACE = 10
HEADER_SPACE = 14
GUTTER = 2.5
SPECIAL_NAMES = {
    "farfetchd": "Farfetch'd", "sirfetchd": "Sirfetch'd",
    "mrmime": "Mr. Mime", "mrrime": "Mr. Rime", "mimejr": "Mime Jr.",
    "typenull": "Type: Null", "flabebe": "Flabébé",
    "nidoranf": "Nidoran (F)", "nidoranm": "Nidoran (M)",
    "porygonz": "Porygon-Z", "jangmoo": "Jangmo-o",
    "hakamoo": "Hakamo-o", "kommoo": "Kommo-o", "hooh": "Ho-Oh",
    "wochien": "Wo-Chien", "chienpao": "Chien-Pao",
    "tinglu": "Ting-Lu", "chiyu": "Chi-Yu",
}


class InputError(ValueError):
    """Invalid or unmatched input."""


@dataclass(frozen=True)
class Entry:
    number: int
    name: str


@dataclass(frozen=True)
class Layout:
    columns: int
    rows: int
    font_size: float
    row_height: float
    column_width: float
    number_font: float
    name_offset: float


class CsvWatcher:
    """Detect edits, including saves that replace the file atomically."""

    def __init__(self) -> None:
        self.last_snapshot: tuple[str, bytes | None] | None = None

    def changed(self, path: Path) -> bool:
        try:
            content = path.read_bytes()
        except OSError:
            content = None
        snapshot = (str(path), content)
        if snapshot == self.last_snapshot:
            return False
        self.last_snapshot = snapshot
        return True


def normalize(name: str) -> str:
    name = name.strip().replace("♀", "f").replace("♂", "m")
    name = unicodedata.normalize("NFKD", name).casefold()
    return "".join(ch for ch in name if ch.isascii() and ch.isalnum())


def display_name(identifier: str) -> str:
    return SPECIAL_NAMES.get(normalize(identifier), identifier.replace("-", " ").title())


def load_species(path: Path = DATA_FILE) -> dict[str, Entry]:
    species = {}
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            entry = Entry(int(row["number"]), display_name(row["name"]))
            for spelling in (row["name"], entry.name):
                species[normalize(spelling)] = entry
    return species


def read_names(path: Path, species: dict[str, Entry]) -> list[Entry]:
    entries = []
    unknown = []
    first_row = True
    with path.open(encoding="utf-8-sig", newline="") as source:
        for line_number, row in enumerate(csv.reader(source), 1):
            if not row or all(not cell.strip() for cell in row):
                continue
            cells = [cell.strip() for cell in row]
            headings = [normalize(cell) for cell in cells]
            if first_row and (headings == ["number", "name"] or
                              headings in (["name"], ["pokemon"], ["pokemonname"])):
                first_row = False
                continue
            first_row = False
            if len(cells) == 1:
                number, name = None, cells[0]
            elif len(cells) == 2 and cells[0].isdigit():
                number, name = int(cells[0]), cells[1]
            else:
                raise InputError(f"Line {line_number}: expected a name or a number,name row.")
            entry = species.get(normalize(name))
            if entry is None:
                unknown.append(f"line {line_number}: {name}")
            elif number is not None and number != entry.number:
                raise InputError(
                    f"Line {line_number}: {name} is National Dex #{entry.number:04d}, "
                    f"but the CSV says #{number:04d}."
                )
            else:
                entries.append(entry)
    if unknown:
        shown = "\n".join(unknown[:12])
        extra = f"\n…and {len(unknown) - 12} more" if len(unknown) > 12 else ""
        raise InputError(f"Unknown Pokémon name(s):\n{shown}{extra}\n\nCorrect the CSV and try again.")
    if not entries:
        raise InputError("The CSV contains no Pokémon names.")
    return sorted(entries, key=lambda entry: (entry.name.casefold(), entry.number))


def choose_layout(entries: list[Entry], page_size: tuple[float, float]) -> Layout:
    width, height = page_size
    usable_width = width - 2 * MARGIN
    usable_height = height - 2 * MARGIN - TITLE_SPACE - FOOTER_SPACE - HEADER_SPACE
    # Try the largest type first. More columns are added only when necessary.
    for step in range(39):
        font_size = 12 - step * 0.25
        row_height = font_size + max(0.8, font_size * 0.15)
        max_rows = math.floor(usable_height / row_height)
        number_font = max(2.5, font_size - 0.5)
        number_width = stringWidth("0000", "Helvetica", number_font)
        name_offset = 3.5 + number_width
        widest_name = max(stringWidth(entry.name, "Helvetica", font_size) for entry in entries)
        for columns in range(2, 21):
            rows = math.ceil(len(entries) / columns)
            if rows > max_rows:
                continue
            column_width = (usable_width - (columns - 1) * GUTTER) / columns
            if name_offset + widest_name + 1.5 <= column_width:
                return Layout(columns, rows, font_size, row_height, column_width,
                              number_font, name_offset)
    raise InputError("This list is too large to place on one page, even at the smallest font size.")


def create_pdf(entries: list[Entry], destination: Path | io.BytesIO,
               page_size: tuple[float, float]) -> Layout:
    layout = choose_layout(entries, page_size)
    width, height = page_size
    pdf = canvas.Canvas(destination if isinstance(destination, io.BytesIO) else str(destination),
                        pagesize=page_size)
    pdf.setTitle("Alphabetical Pokémon list")
    pdf.setAuthor("Printable Pokédex")
    pdf.setFillColor(colors.HexColor("#17263D"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(MARGIN, height - MARGIN - 13, "POKÉMON FIND LIST")
    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(colors.HexColor("#526276"))
    pdf.drawString(MARGIN, height - MARGIN - 27,
                   f"A–Z  •  {len(entries)} names  •  National Dex numbers")
    pdf.setStrokeColor(colors.HexColor("#8795A6"))
    pdf.line(MARGIN, height - MARGIN - 33, width - MARGIN, height - MARGIN - 33)

    top = height - MARGIN - TITLE_SPACE
    for col in range(layout.columns):
        group = entries[col * layout.rows:(col + 1) * layout.rows]
        if not group:
            break
        x = MARGIN + col * (layout.column_width + GUTTER)
        first, last = group[0].name[0].upper(), group[-1].name[0].upper()
        label = first if first == last else f"{first}–{last}"
        pdf.setFillColor(colors.HexColor("#E6ECF3"))
        pdf.roundRect(x, top - 12, layout.column_width, 12, 2, stroke=0, fill=1)
        pdf.setFillColor(colors.HexColor("#17263D"))
        pdf.setFont("Helvetica-Bold", min(8, layout.font_size + 1))
        pdf.drawString(x + 2, top - 9, label)
        for row, entry in enumerate(group):
            row_top = top - HEADER_SPACE - row * layout.row_height
            y = row_top - layout.font_size - 0.2
            if row % 2:
                pdf.setFillColor(colors.HexColor("#F4F6F9"))
                pdf.rect(x, row_top - layout.row_height, layout.column_width,
                         layout.row_height, stroke=0, fill=1)
            pdf.setFillColor(colors.HexColor("#526276"))
            pdf.setFont("Helvetica", layout.number_font)
            pdf.drawString(x + 1.5, y, f"{entry.number:04d}")
            pdf.setFillColor(colors.HexColor("#17263D"))
            pdf.setFont("Helvetica", layout.font_size)
            pdf.drawString(x + layout.name_offset, y, entry.name)
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.HexColor("#6B7888"))
    pdf.drawRightString(width - MARGIN, MARGIN - 3, "Printable Pokédex")
    pdf.showPage()
    pdf.save()
    return layout


class PreviewError(RuntimeError):
    """The PDF page could not be rasterized for the live preview."""


def render_pdf_image(pdf_bytes: bytes, dpi: int = 180) -> Image.Image:
    """Rasterize the actual PDF page, not a separate approximation of it."""
    try:
        import pymupdf
    except ImportError:
        if shutil.which("pdftoppm") is None:
            raise PreviewError("Install PyMuPDF to display the PDF page preview.") from None
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "preview.pdf"
            image_root = Path(directory) / "preview"
            pdf_path.write_bytes(pdf_bytes)
            try:
                subprocess.run(
                    ["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-r", str(dpi),
                     "-png", str(pdf_path), str(image_root)],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                raise PreviewError(f"Could not render the PDF preview: {exc}") from exc
            with Image.open(image_root.with_suffix(".png")) as image:
                return image.convert("RGB")
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            pixmap = document[0].get_pixmap(dpi=dpi, alpha=False)
            return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except Exception as exc:
        raise PreviewError(f"Could not render the PDF preview: {exc}") from exc


def create_preview_image(entries: list[Entry],
                         page_size: tuple[float, float]) -> tuple[Layout, Image.Image]:
    pdf_bytes = io.BytesIO()
    layout = create_pdf(entries, pdf_bytes, page_size)
    return layout, render_pdf_image(pdf_bytes.getvalue())


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("Printable Pokédex")
        root.minsize(760, 560)
        self.csv_path = StringVar()
        self.page_name = StringVar(value="US Letter")
        self.zoom_name = StringVar(value="Fit width")
        self.status = StringVar(value="Edit and save missing_pokemon.csv to update the preview.")
        self.species = load_species()
        self.watcher = CsvWatcher()
        self.preview_image: Image.Image | None = None
        self.photo_image: ImageTk.PhotoImage | None = None
        self.preview_message = "Choose a CSV to preview."
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Printable Pokédex", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Edit missing_pokemon.csv in your text editor. Save it to update this preview.").pack(anchor="w", pady=(4, 18))
        ttk.Label(frame, text="Pokémon CSV").pack(anchor="w")
        picker = ttk.Frame(frame)
        picker.pack(fill="x", pady=(5, 0))
        ttk.Entry(picker, textvariable=self.csv_path).pack(side="left", fill="x", expand=True)
        ttk.Button(picker, text="Browse…", command=self.browse).pack(side="left", padx=(8, 0))
        settings = ttk.Frame(frame)
        settings.pack(fill="x", pady=(18, 0))
        ttk.Label(settings, text="Paper size").pack(side="left", padx=(0, 10))
        ttk.Combobox(settings, textvariable=self.page_name, values=list(PAGES),
                     state="readonly", width=12).pack(side="left")
        ttk.Button(settings, text="Create PDF…", command=self.save).pack(side="right")
        preview_heading = ttk.Frame(frame)
        preview_heading.pack(fill="x", pady=(22, 5))
        ttk.Label(preview_heading, text="Live PDF page preview",
                  font=("TkDefaultFont", 10, "bold")).pack(side="left")
        ttk.Combobox(preview_heading, textvariable=self.zoom_name,
                     values=["Fit width", "100%", "150%", "200%"],
                     state="readonly", width=10).pack(side="right")
        ttk.Label(preview_heading, text="Zoom").pack(side="right", padx=(0, 8))
        preview_frame = ttk.Frame(frame)
        preview_frame.pack(fill="both", expand=True)
        self.preview = Canvas(preview_frame, background="#DCE2E9", highlightthickness=0)
        vertical = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview.yview)
        horizontal = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview.bind("<Configure>", lambda _: self.redraw_preview())
        self.preview.bind("<MouseWheel>", lambda event: self.preview.yview_scroll(
            -1 if event.delta > 0 else 1, "units"))
        self.preview.bind("<Button-4>", lambda _: self.preview.yview_scroll(-1, "units"))
        self.preview.bind("<Button-5>", lambda _: self.preview.yview_scroll(1, "units"))
        ttk.Label(frame, textvariable=self.status, wraplength=520).pack(anchor="w", pady=(12, 0))
        self.page_name.trace_add("write", lambda *_: self.update_preview() if self.csv_path.get() else None)
        self.zoom_name.trace_add("write", lambda *_: self.redraw_preview())
        self.csv_path.trace_add("write", lambda *_: self.path_changed())
        if DEFAULT_INPUT.is_file():
            self.csv_path.set(str(DEFAULT_INPUT))
        else:
            root.after_idle(self.browse)
        root.after(500, self.check_for_changes)

    def path_changed(self) -> None:
        self.watcher.changed(Path(self.csv_path.get().strip()))
        self.update_preview()

    def check_for_changes(self) -> None:
        if self.watcher.changed(Path(self.csv_path.get().strip())):
            self.update_preview()
        self.root.after(500, self.check_for_changes)

    def browse(self) -> None:
        chosen = filedialog.askopenfilename(title="Choose a Pokémon CSV",
                                            filetypes=[("CSV files", "*.csv"), ("All files", "*")])
        if chosen:
            self.csv_path.set(chosen)

    def get_entries(self) -> list[Entry]:
        path = Path(self.csv_path.get().strip())
        if not path.is_file():
            raise InputError("Choose an existing CSV file first.")
        return read_names(path, self.species)

    def update_preview(self) -> None:
        try:
            entries = self.get_entries()
            layout, self.preview_image = create_preview_image(
                entries, PAGES[self.page_name.get()])
        except (OSError, UnicodeError, csv.Error, InputError, PreviewError) as exc:
            self.preview_image = None
            self.preview_message = str(exc)
            self.status.set(str(exc))
        else:
            self.preview_message = ""
            self.status.set(
                f"{len(entries)} names • {layout.columns} columns • "
                f"{layout.font_size:g} pt • one {self.page_name.get()} page"
            )
        self.redraw_preview()

    def redraw_preview(self) -> None:
        view = self.preview
        view.delete("all")
        if self.preview_image is None:
            self.photo_image = None
            view.create_text(
                20, 20, anchor="nw", text=self.preview_message,
                width=max(300, view.winfo_width() - 40),
                fill="#17263D", font=("TkDefaultFont", 11, "bold"),
            )
            view.configure(scrollregion=(0, 0, view.winfo_width(), view.winfo_height()))
            return

        image = self.preview_image
        zoom = self.zoom_name.get()
        if zoom == "Fit width":
            factor = max(0.1, (view.winfo_width() - 32) / image.width)
        else:
            # One PDF point occupies 1⅓ screen pixels at 100% zoom.
            page_width = PAGES[self.page_name.get()][0]
            target_width = page_width * (96 / 72) * (int(zoom.rstrip("%")) / 100)
            factor = target_width / image.width
        display_width = max(1, round(image.width * factor))
        display_height = max(1, round(image.height * factor))
        displayed = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.photo_image = ImageTk.PhotoImage(displayed)
        left = max(16, (view.winfo_width() - display_width) // 2)
        top = 14
        view.create_image(left, top, anchor="nw", image=self.photo_image)
        view.configure(scrollregion=(0, 0,
                                     max(view.winfo_width(), left + display_width + 16),
                                     top + display_height + 16))

    def save(self) -> None:
        try:
            entries = self.get_entries()
            choose_layout(entries, PAGES[self.page_name.get()])
        except (OSError, UnicodeError, csv.Error, InputError) as exc:
            messagebox.showerror("Cannot create PDF", str(exc))
            self.status.set(str(exc))
            return
        default = Path(self.csv_path.get()).stem + "-alphabetical.pdf"
        chosen = filedialog.asksaveasfilename(title="Save printable PDF", defaultextension=".pdf",
                                              initialfile=default, filetypes=[("PDF files", "*.pdf")])
        if not chosen:
            return
        try:
            create_pdf(entries, Path(chosen), PAGES[self.page_name.get()])
        except OSError as exc:
            messagebox.showerror("Could not save PDF", str(exc))
            return
        self.status.set(f"Saved {len(entries)} names to {chosen}")
        messagebox.showinfo("PDF ready", f"Saved to:\n{chosen}\n\nOpen the PDF and print at actual size.")


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
