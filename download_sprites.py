"""Cache default Pokémon sprites by National Dex number for offline PDFs."""

import argparse
import csv
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image


HERE = Path(__file__).resolve().parent
CATALOG = HERE / "pokemon_species.csv"
SPRITE_DIR = HERE / "sprites"
BASE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"


def species_numbers() -> list[int]:
    with CATALOG.open(encoding="utf-8", newline="") as source:
        return sorted({int(row["number"]) for row in csv.DictReader(source)})


def download_one(number: int) -> tuple[int, str]:
    destination = SPRITE_DIR / f"{number}.png"
    if destination.is_file():
        return number, "cached"
    request = Request(f"{BASE_URL}/{number}.png",
                      headers={"User-Agent": "printable-pokedex-sprite-cache/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("response is not a valid sprite PNG")
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        temporary = destination.with_suffix(".png.tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        return number, "downloaded"
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return number, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("numbers", nargs="*", type=int,
                        help="specific National Dex numbers; default: all species")
    parser.add_argument("--jobs", type=int, default=8,
                        help="simultaneous downloads (default: 8)")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    numbers = sorted(set(args.numbers)) if args.numbers else species_numbers()
    if any(number < 1 for number in numbers):
        parser.error("National Dex numbers must be positive")
    SPRITE_DIR.mkdir(exist_ok=True)
    counts = {"cached": 0, "downloaded": 0}
    failures = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for index, future in enumerate(as_completed(
            executor.submit(download_one, number) for number in numbers
        ), 1):
            number, result = future.result()
            if result in counts:
                counts[result] += 1
            else:
                failures.append((number, result))
            if index % 100 == 0 or index == len(numbers):
                print(f"{index}/{len(numbers)} checked: "
                      f"{counts['downloaded']} downloaded, {counts['cached']} cached, "
                      f"{len(failures)} unavailable", flush=True)
    for number, reason in sorted(failures):
        print(f"#{number:04d}: {reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
