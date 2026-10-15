# Printable Pokédex

Turn an editable CSV of Pokémon and forms you still need into a one-page PDF with National Dex numbers. Sort by National Dex number or alphabetically. The live preview is an image rendered from the actual PDF page. The app uses a bundled catalog, so creating sheets works offline.

## Install

Python 3.10 or newer is required. On Linux, install Tkinter for your Python distribution if it is not already present.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead.

## Run

```bash
python main.py
```

Open [missing_pokemon.csv](missing_pokemon.csv) in your text editor. It starts with all **1,025 ordinary species in National Dex order, followed by 623 forms in National Dex order**, one name per line and no header. Forms of the same species are ordered by form name. Delete entries you already have; add one back on its own line if you need it again. This is your working list. [pokemon_species.csv](pokemon_species.csv) is the numbered master catalog, with `number,name,form` columns. Every species has one blank `form` cell for its ordinary entry. Form rows use the same National Dex number as their species.

Run the app and leave it open while you edit. It automatically loads `missing_pokemon.csv` from the repo and watches for saved changes. After each save, it rebuilds the PDF page image and shows the updated sheet. Use the zoom control and scrollbars to inspect the dense layout. If the file is missing, the app opens a file picker; you can also use **Browse** at any time. Pick US Letter, A4, Tabloid, or A3, then click **Create PDF**. The PDF uses the latest saved CSV and the current sort and form settings. Open it and print at actual size.

## Sort and form controls

Choose **National Dex** or **Alphabetical** from **Sort by**. With **Separate regular Pokémon and forms** checked, the sheet lists all ordinary species first, then forms in a second sequence using the same sort order. Uncheck it to place each species' forms beside that species in the sorted sequence.

**Include forms** switches all forms on or off. While it is on, the **Gigantamax**, **Mega**, **Regional**, and **Other** checkboxes select which forms appear in the preview and PDF. Regional includes Alolan, Galarian, Hisuian, and Paldean variants; Other includes colors, Rotom appliances, seasonal forms, and remaining named forms. The four groups are mutually exclusive, so selecting all four includes every named form in the master catalog.

Click **Advanced form settings…** to refine **Other**. Search for a species or form, select a species on the left, then check the individual variants you want on the right. You can select or clear all Other forms for one species (such as Alcremie, Unown, or Deoxys) or for the whole Other category. Alcremie's Gigantamax form remains under the separate Gigantamax checkbox. The main window shows how many Other forms are selected. **Apply** updates the live preview, PDF, and any CSV you generate next; **Cancel** leaves the selection unchanged. Unchecking **Other** temporarily hides that category without erasing your advanced selections. These settings filter entries; they do not delete lines from your editable CSV.

Click **Generate editable CSV…** to make a fresh list from `pokemon_species.csv` using the current controls. The save dialog proposes a `missing_pokemon_<selection>.csv` filename; choose a new name to keep your existing edited list. The app opens the new CSV after saving it. Generated files contain one Pokémon or form name per line, ready for you to delete entries you already own. Generating from the master includes all selected entries again, including any you deleted from another working list.

The working CSV looks like this:

```csv
Bulbasaur
Pikachu
Mr. Mime
Flabébé
Raichu (Alolan Form)
Charizard (Mega X)
Pikachu (Gigantamax Form)
Squawkabilly (Yellow Plumage)
Deerling (Winter Form)
Burmy (Sandy Cloak)
Rotom (Heat)
```

Plain names such as `Raichu` are still accepted. To include a particular form, copy its species and form from the master into `Species (Form)` format, as above. Ordinary Dynamax is omitted; named Gigantamax forms are included.

Rows can be in any order; the preview and PDF apply the chosen sort order and add National Dex numbers. Unknown names are reported with line numbers. Blank rows are ignored. Duplicate names are kept as separate entries. The PDF has no page title or footer; its columns extend close to the bottom edge. The layout changes the font size and number of columns to fit the list on one page. All 1,025 plain species fit on Letter or A4 at about 5.75–6 points. Adding every catalogued form makes the type roughly 3–3.25 points on those sizes, which will be very hard to read. Tabloid and A3 allow about 5.5 points for that full list. The PDF reads down each column, then continues at the top of the next column.

The bundled reference contains 1,648 entries: one ordinary entry for each of 1,025 species and 623 named forms. Its source data comes from PokéAPI's [Pokémon forms](https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_forms.csv), [English form names](https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_form_names.csv), [Pokémon IDs](https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon.csv), and [English species names](https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_species_names.csv) tables. Some entries use PokéAPI identifiers where its form name is absent or ambiguous.
