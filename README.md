# Printable Pokédex

Turn an editable CSV of Pokémon you still need into a one-page alphabetical PDF with National Dex numbers. The live preview is an image rendered from the actual PDF page. The app uses a bundled PokéAPI species list, so creating sheets works offline.

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

Open [missing_pokemon.csv](missing_pokemon.csv) in your text editor. It contains **one Pokémon name per line**, with no header. Delete names you already have; add a name back on its own line if you need it again. This is your working list. [pokemon_species.csv](pokemon_species.csv) remains the complete numbered reference.

Run the app and leave it open while you edit. It automatically loads `missing_pokemon.csv` from the repo and watches for saved changes. After each save, it rebuilds the PDF page image and shows the updated sheet. Use the zoom control and scrollbars to inspect the dense layout. If the file is missing, the app opens a file picker; you can also use **Browse** at any time. Pick US Letter or A4, then click **Create PDF**. The PDF uses the latest saved CSV. Open it and print at actual size.

The working CSV looks like this:

```csv
Bulbasaur
Pikachu
Mr. Mime
Flabébé
```

Rows can be in any order; the preview and PDF sort them A–Z and add National Dex numbers. Unknown names are reported with line numbers. Blank rows are ignored. Duplicate names are kept as separate entries. The layout changes the font size and number of columns to fit the list on one page, including all 1,025 species. With all species on Letter or A4 paper, the text is about 5.75 points and may be difficult to read without magnification. The PDF reads down each column, then continues at the top of the next column.

National Dex data: [PokéAPI Pokémon species CSV](https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_species.csv).
