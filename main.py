"""Create a one-page Pokémon list from an editable CSV."""

import csv
import io
import math
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, Canvas, Tk, StringVar, Toplevel, filedialog, messagebox, ttk

from PIL import Image, ImageTk

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, TABLOID, letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


DATA_FILE = Path(__file__).with_name("pokemon_species.csv")
DEFAULT_INPUT = Path(__file__).with_name("missing_pokemon.csv")
PAGES = {"US Letter": letter, "A4": A4, "Tabloid": TABLOID, "A3": A3}
MARGIN = 18
TOP_MARGIN = 12
BOTTOM_MARGIN = 12
HEADER_SPACE = 14
GUTTER = 2.5
SORT_ORDERS = ("National Dex", "Alphabetical")
FORM_CATEGORIES = ("Gigantamax", "Mega", "Regional", "Other")
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
    form: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.form})" if self.form else self.name


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
    # Keep punctuation that distinguishes forms such as Unown (!) and Unown (?).
    return "".join(ch for ch in name if ch.isascii() and (ch.isalnum() or ch in "!?"))


def display_name(identifier: str) -> str:
    return SPECIAL_NAMES.get(normalize(identifier), identifier.replace("-", " ").title())


def load_catalog(path: Path = DATA_FILE) -> list[Entry]:
    entries = []
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            entries.append(Entry(int(row["number"]), display_name(row["name"]), row.get("form", "")))
    return entries


def load_species(path: Path = DATA_FILE) -> dict[str, Entry]:
    species = {}
    for entry in load_catalog(path):
        # Plain names in existing missing lists remain species entries.
        # A parenthesized form name selects the exact variant.
        species.setdefault(normalize(entry.name), Entry(entry.number, entry.name))
        species[normalize(entry.label)] = entry
        if entry.form.endswith((" Form", " Forme", " Mode")):
            short_form = entry.form.rsplit(" ", 1)[0]
            species.setdefault(normalize(f"{entry.name} {short_form}"), entry)
    return species


def form_category(entry: Entry) -> str:
    """Assign every named form to one generator filter."""
    form = entry.form.casefold()
    if "gigantamax" in form:
        return "Gigantamax"
    if "mega" in form:
        return "Mega"
    if any(region in form for region in ("alolan", "galarian", "hisuian", "paldean")):
        return "Regional"
    return "Other"


def form_key(entry: Entry) -> tuple[int, str]:
    return entry.number, entry.form


def other_form_groups(catalog: list[Entry]) -> dict[int, list[Entry]]:
    """Group the Other variants by species for the advanced selector."""
    groups: dict[int, list[Entry]] = {}
    others = sorted((entry for entry in catalog if entry.form and
                     form_category(entry) == "Other"),
                    key=lambda entry: (entry.name.casefold(), entry.form.casefold()))
    for entry in others:
        groups.setdefault(entry.number, []).append(entry)
    return groups


def filter_entries(entries: list[Entry], include_forms: bool = True,
                   categories: set[str] | None = None,
                   other_forms: set[tuple[int, str]] | None = None,
                   include_regular: bool = True) -> list[Entry]:
    selected = set(FORM_CATEGORIES) if categories is None else categories
    filtered = []
    for entry in entries:
        if not entry.form:
            if include_regular:
                filtered.append(entry)
            continue
        if include_forms:
            category = form_category(entry)
            if category in selected and (category != "Other" or other_forms is None or
                                         form_key(entry) in other_forms):
                filtered.append(entry)
    return filtered


def sort_entries(entries: list[Entry], order: str = "National Dex",
                 separate_forms: bool = True) -> list[Entry]:
    """Sort by Dex or name, with optional regular-species and forms sections."""
    if order not in SORT_ORDERS:
        raise ValueError(f"Unknown sort order: {order}")
    if order == "National Dex":
        key = lambda entry: (entry.number, bool(entry.form), entry.form.casefold(), entry.name.casefold())
    else:
        key = lambda entry: (entry.name.casefold(), bool(entry.form), entry.form.casefold(), entry.number)
    if separate_forms:
        return sorted(entries, key=lambda entry: (bool(entry.form), *key(entry)))
    return sorted(entries, key=key)


def write_editable_csv(path: Path, entries: list[Entry]) -> None:
    """Write a one-name-per-line list ready for subtractive editing."""
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerows([entry.label] for entry in entries)


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
            if first_row and (headings in (["number", "name"], ["number", "name", "form"]) or
                              headings in (["name"], ["pokemon"], ["pokemonname"])):
                first_row = False
                continue
            first_row = False
            if len(cells) == 1:
                number, name = None, cells[0]
            elif len(cells) == 2 and cells[0].isdigit():
                number, name = int(cells[0]), cells[1]
            elif len(cells) == 3 and cells[0].isdigit():
                number = int(cells[0])
                name = f"{cells[1]} ({cells[2]})" if cells[2] else cells[1]
            else:
                raise InputError(
                    f"Line {line_number}: expected a name, number,name, or number,name,form row."
                )
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
    return sort_entries(entries)


def choose_layout(entries: list[Entry], page_size: tuple[float, float]) -> Layout:
    width, height = page_size
    usable_width = width - 2 * MARGIN
    usable_height = height - TOP_MARGIN - BOTTOM_MARGIN - HEADER_SPACE
    # Try the largest type first. More columns are added only when necessary.
    for step in range(39):
        font_size = 12 - step * 0.25
        row_height = font_size + max(0.8, font_size * 0.15)
        max_rows = math.floor(usable_height / row_height)
        number_font = max(2.5, font_size - 0.5)
        number_width = stringWidth("0000", "Helvetica", number_font)
        name_offset = 3.5 + number_width
        widest_plain = max(
            (stringWidth(entry.label, "Helvetica", 1) for entry in entries if not entry.form),
            default=0,
        )
        widest_form = max(
            (stringWidth(entry.label, "Helvetica", 1) for entry in entries if entry.form),
            default=0,
        )
        minimum_name_font = max(2.5, font_size * 0.55)
        for columns in range(2, 21):
            rows = math.ceil(len(entries) / columns)
            if rows > max_rows:
                continue
            column_width = (usable_width - (columns - 1) * GUTTER) / columns
            needed = max(widest_plain * font_size, widest_form * minimum_name_font)
            if name_offset + needed + 1.5 <= column_width:
                # Spread a dense list down to the printable bottom edge.
                drawn_row_height = usable_height / rows if rows >= 30 else row_height
                return Layout(columns, rows, font_size, drawn_row_height, column_width,
                              number_font, name_offset)
    raise InputError("This list is too large to place on one page, even at the smallest font size.")


def column_heading(group: list[Entry], order: str, separate_forms: bool) -> tuple[str, int | None]:
    first_form = next((i for i, entry in enumerate(group) if entry.form), None)

    def range_label(first: Entry, last: Entry) -> str:
        if order == "National Dex":
            return f"{first.number:04d}" if first.number == last.number else f"{first.number:04d}–{last.number:04d}"
        start, end = first.name[0].upper(), last.name[0].upper()
        return start if start == end else f"{start}–{end}"

    if not separate_forms or first_form is None:
        return range_label(group[0], group[-1]), None
    if first_form == 0:
        return f"FORMS {range_label(group[0], group[-1])}", None
    return f"{range_label(group[0], group[first_form - 1])} / FORMS", first_form


def create_pdf(entries: list[Entry], destination: Path | io.BytesIO,
               page_size: tuple[float, float], order: str = "National Dex",
               separate_forms: bool = True) -> Layout:
    entries = sort_entries(entries, order, separate_forms)
    layout = choose_layout(entries, page_size)
    _, height = page_size
    pdf = canvas.Canvas(destination if isinstance(destination, io.BytesIO) else str(destination),
                        pagesize=page_size)
    pdf.setTitle(f"{order} Pokémon list")
    pdf.setAuthor("Printable Pokédex")
    top = height - TOP_MARGIN
    for col in range(layout.columns):
        group = entries[col * layout.rows:(col + 1) * layout.rows]
        if not group:
            break
        x = MARGIN + col * (layout.column_width + GUTTER)
        label, form_boundary = column_heading(group, order, separate_forms)
        pdf.setFillColor(colors.HexColor("#E6ECF3"))
        pdf.roundRect(x, top - 12, layout.column_width, 12, 2, stroke=0, fill=1)
        pdf.setFillColor(colors.HexColor("#17263D"))
        header_width = stringWidth(label, "Helvetica-Bold", 1)
        pdf.setFont("Helvetica-Bold", min(8, layout.font_size + 1,
                                           (layout.column_width - 4) / header_width))
        pdf.drawString(x + 2, top - 9, label)
        for row, entry in enumerate(group):
            row_top = top - HEADER_SPACE - row * layout.row_height
            if row % 2:
                pdf.setFillColor(colors.HexColor("#F4F6F9"))
                pdf.rect(x, row_top - layout.row_height, layout.column_width,
                         layout.row_height, stroke=0, fill=1)
            if row and row == form_boundary:
                pdf.setStrokeColor(colors.HexColor("#8795A6"))
                pdf.line(x, row_top, x + layout.column_width, row_top)
            pdf.setFillColor(colors.HexColor("#526276"))
            pdf.setFont("Helvetica", layout.number_font)
            number_y = row_top - (layout.row_height + layout.number_font) / 2
            pdf.drawString(x + 1.5, number_y, f"{entry.number:04d}")
            pdf.setFillColor(colors.HexColor("#17263D"))
            available = layout.column_width - layout.name_offset - 1.5
            unit_width = stringWidth(entry.label, "Helvetica", 1)
            name_font = min(layout.font_size, available / unit_width)
            name_y = row_top - (layout.row_height + name_font) / 2
            pdf.setFont("Helvetica", name_font)
            pdf.drawString(x + layout.name_offset, name_y, entry.label)
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
                         page_size: tuple[float, float], order: str = "National Dex",
                         separate_forms: bool = True) -> tuple[Layout, Image.Image]:
    pdf_bytes = io.BytesIO()
    layout = create_pdf(entries, pdf_bytes, page_size, order, separate_forms)
    return layout, render_pdf_image(pdf_bytes.getvalue())


class OtherFormsDialog:
    """Choose Other forms by species or by individual variant."""

    def __init__(self, parent: Tk, catalog: list[Entry],
                 selected: set[tuple[int, str]] | None,
                 on_apply: Callable[[set[tuple[int, str]] | None], None]) -> None:
        self.groups = other_form_groups(catalog)
        self.all_keys = {form_key(entry) for forms in self.groups.values() for entry in forms}
        self.selected = set(self.all_keys if selected is None else selected) & self.all_keys
        self.on_apply = on_apply
        self.window = Toplevel(parent)
        self.window.title("Advanced form settings")
        self.window.geometry("850x620")
        self.window.minsize(650, 450)
        self.window.transient(parent)
        self.window.bind("<Escape>", lambda _: self.window.destroy())

        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Choose Other forms", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Select a Pokémon, then choose its individual forms. These choices filter the preview, PDF, and new CSVs.",
                  wraplength=790).pack(anchor="w", pady=(4, 12))
        search_row = ttk.Frame(outer)
        search_row.pack(fill="x", pady=(0, 10))
        ttk.Label(search_row, text="Find species or form").pack(side="left", padx=(0, 8))
        self.search = StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search)
        search_entry.pack(side="left", fill="x", expand=True)

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        species_frame = ttk.Frame(body)
        species_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        species_frame.columnconfigure(0, weight=1)
        species_frame.rowconfigure(0, weight=1)
        self.species = ttk.Treeview(species_frame, columns=("selected",), show="tree headings",
                                    selectmode="browse")
        self.species.heading("#0", text="Pokémon")
        self.species.heading("selected", text="Forms")
        self.species.column("#0", width=170, minwidth=110)
        self.species.column("selected", width=75, minwidth=65, anchor="center", stretch=False)
        species_scroll = ttk.Scrollbar(species_frame, orient="vertical", command=self.species.yview)
        self.species.configure(yscrollcommand=species_scroll.set)
        self.species.grid(row=0, column=0, sticky="nsew")
        species_scroll.grid(row=0, column=1, sticky="ns")
        self.species.bind("<<TreeviewSelect>>", lambda _: self.show_species())

        forms_frame = ttk.Frame(body)
        forms_frame.grid(row=0, column=1, sticky="nsew")
        forms_frame.columnconfigure(0, weight=1)
        forms_frame.rowconfigure(2, weight=1)
        self.species_label = StringVar(value="Select a Pokémon")
        ttk.Label(forms_frame, textvariable=self.species_label,
                  font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        group_actions = ttk.Frame(forms_frame)
        group_actions.grid(row=1, column=0, sticky="w", pady=(7, 7))
        ttk.Button(group_actions, text="Select all for species",
                   command=lambda: self.set_species(True)).pack(side="left")
        ttk.Button(group_actions, text="Clear species",
                   command=lambda: self.set_species(False)).pack(side="left", padx=(8, 0))
        list_frame = ttk.Frame(forms_frame)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.form_canvas = Canvas(list_frame, highlightthickness=0)
        form_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.form_canvas.yview)
        self.form_canvas.configure(yscrollcommand=form_scroll.set)
        self.form_canvas.grid(row=0, column=0, sticky="nsew")
        form_scroll.grid(row=0, column=1, sticky="ns")
        self.form_frame = ttk.Frame(self.form_canvas, padding=(6, 4))
        self.form_window = self.form_canvas.create_window((0, 0), window=self.form_frame, anchor="nw")
        self.form_frame.bind("<Configure>", lambda _: self.form_canvas.configure(
            scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>", lambda event: self.form_canvas.itemconfigure(
            self.form_window, width=event.width))
        self.form_canvas.bind("<MouseWheel>", self.scroll_forms)
        self.form_canvas.bind("<Button-4>", self.scroll_forms)
        self.form_canvas.bind("<Button-5>", self.scroll_forms)
        self.child_vars: list[BooleanVar] = []

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        self.count_label = StringVar()
        ttk.Label(footer, textvariable=self.count_label).pack(side="left")
        ttk.Button(footer, text="Select all Other", command=lambda: self.set_all(True)).pack(
            side="left", padx=(14, 0))
        ttk.Button(footer, text="Clear all Other", command=lambda: self.set_all(False)).pack(
            side="left", padx=(7, 0))
        ttk.Button(footer, text="Apply", command=self.apply).pack(side="right")
        ttk.Button(footer, text="Cancel", command=self.window.destroy).pack(side="right", padx=(0, 8))

        self.search.trace_add("write", lambda *_: self.refresh_species())
        self.refresh_species()
        self.update_count()
        self.window.wait_visibility()
        self.window.grab_set()
        search_entry.focus_set()

    def scroll_forms(self, event) -> None:
        direction = -1 if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0 else 1
        self.form_canvas.yview_scroll(direction, "units")

    def refresh_species(self) -> None:
        previous = self.species.selection()
        previous_id = previous[0] if previous else None
        for item in self.species.get_children():
            self.species.delete(item)
        query = self.search.get().strip().casefold()
        for number, forms in self.groups.items():
            name = forms[0].name
            if query and query not in name.casefold() and not any(
                    query in entry.form.casefold() for entry in forms):
                continue
            count = sum(form_key(entry) in self.selected for entry in forms)
            self.species.insert("", "end", iid=str(number), text=name,
                                values=(f"{count}/{len(forms)}",))
        visible = self.species.get_children()
        if visible:
            chosen = previous_id if previous_id in visible else visible[0]
            self.species.selection_set(chosen)
            self.species.see(chosen)
        self.show_species()

    def show_species(self) -> None:
        for child in self.form_frame.winfo_children():
            child.destroy()
        self.child_vars.clear()
        selection = self.species.selection()
        if not selection:
            self.species_label.set("No matching Pokémon")
            self.form_canvas.yview_moveto(0)
            return
        number = int(selection[0])
        forms = self.groups[number]
        self.species_label.set(f"#{number:04d} {forms[0].name} — {len(forms)} Other forms")
        query = self.search.get().strip().casefold()
        visible = forms if query in forms[0].name.casefold() else [
            entry for entry in forms if query in entry.form.casefold()]
        for entry in visible:
            key = form_key(entry)
            variable = BooleanVar(value=key in self.selected)
            check = ttk.Checkbutton(self.form_frame, text=entry.form, variable=variable,
                                    command=lambda key=key, variable=variable: self.toggle_form(
                                        key, variable.get()))
            check.pack(anchor="w", fill="x", pady=1)
            check.bind("<MouseWheel>", self.scroll_forms)
            check.bind("<Button-4>", self.scroll_forms)
            check.bind("<Button-5>", self.scroll_forms)
            self.child_vars.append(variable)
        self.form_canvas.yview_moveto(0)

    def toggle_form(self, key: tuple[int, str], selected: bool) -> None:
        if selected:
            self.selected.add(key)
        else:
            self.selected.discard(key)
        self.update_count(key[0])

    def update_count(self, number: int | None = None) -> None:
        self.count_label.set(f"{len(self.selected)} of {len(self.all_keys)} Other forms selected")
        numbers = self.groups if number is None else {number: self.groups[number]}
        for species_number, forms in numbers.items():
            if self.species.exists(str(species_number)):
                count = sum(form_key(entry) in self.selected for entry in forms)
                self.species.item(str(species_number), values=(f"{count}/{len(forms)}",))

    def set_species(self, selected: bool) -> None:
        selection = self.species.selection()
        if not selection:
            return
        number = int(selection[0])
        for entry in self.groups[number]:
            key = form_key(entry)
            if selected:
                self.selected.add(key)
            else:
                self.selected.discard(key)
        self.update_count(number)
        self.show_species()

    def set_all(self, selected: bool) -> None:
        self.selected = set(self.all_keys) if selected else set()
        self.update_count()
        self.show_species()

    def apply(self) -> None:
        selected = None if self.selected == self.all_keys else set(self.selected)
        self.window.destroy()
        self.on_apply(selected)


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("Printable Pokédex")
        root.minsize(800, 620)
        self.csv_path = StringVar()
        self.page_name = StringVar(value="US Letter")
        self.zoom_name = StringVar(value="Fit width")
        self.sort_order = StringVar(value="National Dex")
        self.separate_forms = BooleanVar(value=True)
        self.include_regular = BooleanVar(value=True)
        self.include_forms = BooleanVar(value=True)
        self.form_options = {category: BooleanVar(value=True) for category in FORM_CATEGORIES}
        self.other_selected: set[tuple[int, str]] | None = None
        self.other_label = StringVar()
        self.status = StringVar(value="Edit and save missing_pokemon.csv to update the preview.")
        self.catalog = load_catalog()
        self.species = load_species()
        self.update_other_label()
        self.watcher = CsvWatcher()
        self.preview_image: Image.Image | None = None
        self.photo_image: ImageTk.PhotoImage | None = None
        self.preview_message = "Choose a CSV to preview."
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Printable Pokédex", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Edit the selected CSV in your text editor. Save it to update this preview.").pack(anchor="w", pady=(4, 18))
        ttk.Label(frame, text="Pokémon CSV").pack(anchor="w")
        picker = ttk.Frame(frame)
        picker.pack(fill="x", pady=(5, 0))
        ttk.Entry(picker, textvariable=self.csv_path).pack(side="left", fill="x", expand=True)
        ttk.Button(picker, text="Browse…", command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Button(picker, text="Generate editable CSV…", command=self.generate_csv).pack(side="left", padx=(8, 0))
        order_row = ttk.Frame(frame)
        order_row.pack(fill="x", pady=(16, 0))
        ttk.Label(order_row, text="Sort by").pack(side="left", padx=(0, 10))
        ttk.Combobox(order_row, textvariable=self.sort_order, values=SORT_ORDERS,
                     state="readonly", width=15).pack(side="left")
        ttk.Checkbutton(order_row, text="Separate regular Pokémon and forms",
                        variable=self.separate_forms).pack(side="left", padx=(18, 0))
        selection_row = ttk.Frame(frame)
        selection_row.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(selection_row, text="Include regular Pokédex",
                        variable=self.include_regular).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(selection_row, text="Include forms", variable=self.include_forms,
                        command=self.forms_changed).pack(side="left", padx=(0, 12))
        ttk.Button(selection_row, text="Advanced form settings…",
                   command=self.open_advanced_settings).pack(side="right")
        forms_row = ttk.Frame(frame)
        forms_row.pack(fill="x", pady=(8, 0))
        ttk.Label(forms_row, text="Form groups").pack(side="left", padx=(0, 12))
        self.category_checks = []
        for category in FORM_CATEGORIES:
            options = {"textvariable": self.other_label} if category == "Other" else {"text": category}
            check = ttk.Checkbutton(forms_row, variable=self.form_options[category], **options)
            check.pack(side="left", padx=(0, 12))
            self.category_checks.append(check)
        settings = ttk.Frame(frame)
        settings.pack(fill="x", pady=(16, 0))
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
        self.sort_order.trace_add("write", lambda *_: self.update_preview())
        self.separate_forms.trace_add("write", lambda *_: self.update_preview())
        self.include_regular.trace_add("write", lambda *_: self.update_preview())
        for option in self.form_options.values():
            option.trace_add("write", lambda *_: self.update_preview())
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

    def selected_categories(self) -> set[str]:
        return {category for category, option in self.form_options.items() if option.get()}

    def selected_entries(self) -> list[Entry]:
        entries = filter_entries(self.get_entries(), self.include_forms.get(),
                                 self.selected_categories(), self.other_selected,
                                 include_regular=self.include_regular.get())
        if not entries:
            raise InputError("No entries match the current selection. Include regular Pokémon or at least one form group.")
        return entries

    def update_other_label(self) -> None:
        others = [entry for entry in self.catalog if entry.form and
                  form_category(entry) == "Other"]
        selected_count = len(others) if self.other_selected is None else sum(
            form_key(entry) in self.other_selected for entry in others)
        self.other_label.set(f"Other ({selected_count}/{len(others)})")

    def open_advanced_settings(self) -> None:
        try:
            self.catalog = load_catalog()
            self.species = load_species()
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            messagebox.showerror("Could not read master catalog", str(exc))
            return
        self.update_other_label()
        OtherFormsDialog(self.root, self.catalog, self.other_selected,
                         self.apply_other_selection)

    def apply_other_selection(self, selection: set[tuple[int, str]] | None) -> None:
        self.other_selected = selection
        self.update_other_label()
        self.update_preview()

    def forms_changed(self) -> None:
        for check in self.category_checks:
            check.state(["!disabled"] if self.include_forms.get() else ["disabled"])
        self.update_preview()

    def generate_csv(self) -> None:
        try:
            self.catalog = load_catalog()
            self.species = load_species()
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            messagebox.showerror("Could not read master catalog", str(exc))
            return
        self.update_other_label()
        categories = self.selected_categories()
        entries = sort_entries(
            filter_entries(self.catalog, self.include_forms.get(), categories,
                           self.other_selected,
                           include_regular=self.include_regular.get()),
            self.sort_order.get(), self.separate_forms.get(),
        )
        if not entries:
            messagebox.showerror("Cannot create CSV",
                                 "No entries match the current selection. Include regular Pokémon or at least one form group.")
            return
        if not any(entry.form for entry in entries):
            suffix = "species"
        elif categories == set(FORM_CATEGORIES) and self.other_selected is None:
            suffix = "forms" if not self.include_regular.get() else "all"
        else:
            selected_groups = "_".join(category.lower() for category in FORM_CATEGORIES
                                       if category in categories)
            suffix = f"forms_{selected_groups}" if not self.include_regular.get() else selected_groups
            if self.other_selected is not None and "Other" in categories:
                suffix += "_custom"
        chosen = filedialog.asksaveasfilename(
            title="Create editable Pokémon CSV", initialdir=str(DATA_FILE.parent),
            initialfile=f"missing_pokemon_{suffix}.csv", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not chosen:
            return
        destination = Path(chosen)
        if destination.resolve() == DATA_FILE.resolve():
            messagebox.showerror("Choose another filename",
                                 "The master Pokémon catalog cannot be replaced by an editable list.")
            return
        try:
            write_editable_csv(destination, entries)
        except (OSError, UnicodeError, csv.Error) as exc:
            messagebox.showerror("Could not create CSV", str(exc))
            return
        self.csv_path.set(chosen)
        self.status.set(f"Created {len(entries)} editable entries in {destination.name}.")

    def update_preview(self) -> None:
        try:
            entries = self.selected_entries()
            layout, self.preview_image = create_preview_image(
                entries, PAGES[self.page_name.get()], self.sort_order.get(),
                self.separate_forms.get())
        except (OSError, UnicodeError, csv.Error, InputError, PreviewError) as exc:
            self.preview_image = None
            self.preview_message = str(exc)
            self.status.set(str(exc))
        else:
            self.preview_message = ""
            self.status.set(
                f"{len(entries)} entries • {layout.columns} columns • "
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
            entries = self.selected_entries()
            choose_layout(entries, PAGES[self.page_name.get()])
        except (OSError, UnicodeError, csv.Error, InputError) as exc:
            messagebox.showerror("Cannot create PDF", str(exc))
            self.status.set(str(exc))
            return
        suffix = "dex" if self.sort_order.get() == "National Dex" else "alphabetical"
        default = Path(self.csv_path.get()).stem + f"-{suffix}.pdf"
        chosen = filedialog.asksaveasfilename(title="Save printable PDF", defaultextension=".pdf",
                                              initialfile=default, filetypes=[("PDF files", "*.pdf")])
        if not chosen:
            return
        try:
            create_pdf(entries, Path(chosen), PAGES[self.page_name.get()],
                       self.sort_order.get(), self.separate_forms.get())
        except OSError as exc:
            messagebox.showerror("Could not save PDF", str(exc))
            return
        self.status.set(f"Saved {len(entries)} entries to {chosen}")
        messagebox.showinfo("PDF ready", f"Saved to:\n{chosen}\n\nOpen the PDF and print at actual size.")


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
