"""Checks for the editable Pokémon and forms list."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = main.load_catalog()
        cls.lookup = main.load_species()

    def read_lines(self, lines):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.csv"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return main.read_names(path, self.lookup)

    def test_catalog_has_unique_resolvable_forms(self):
        self.assertEqual(len({entry.number for entry in self.catalog}), 1025)
        self.assertEqual(sum(not entry.form for entry in self.catalog), 1025)
        forms = [entry for entry in self.catalog if entry.form]
        self.assertEqual(len(forms), 623)
        self.assertEqual(
            len({(entry.number, entry.form) for entry in forms}), len(forms)
        )
        for entry in forms:
            self.assertEqual(self.lookup[main.normalize(entry.label)], entry)
        self.assertEqual(self.lookup[main.normalize("Unown")].form, "")
        self.assertEqual(self.lookup[main.normalize("Unown (!)")].form, "!")
        self.assertEqual(self.lookup[main.normalize("Unown (?)")].form, "?")

    def test_one_name_per_line_resolves_forms_and_numbers(self):
        entries = self.read_lines([
            "Pikachu", "Pikachu (Gigantamax Form)", "Raichu (Alolan Form)",
            "Growlithe (Hisuian Form)", "Ponyta (Galarian Form)",
            "Squawkabilly (Yellow Plumage)", "Deerling (Winter Form)",
            "Burmy (Sandy Cloak)", "Rotom (Heat)",
        ])
        self.assertEqual(len(entries), 9)
        self.assertIn(main.Entry(25, "Pikachu"), entries)
        self.assertIn(main.Entry(25, "Pikachu", "Gigantamax Form"), entries)
        self.assertIn(main.Entry(931, "Squawkabilly", "Yellow Plumage"), entries)

    def test_catalog_csv_and_form_filters(self):
        entries = self.read_lines([
            "number,name,form", "6,Charizard,Mega X", "25,Pikachu,"
        ])
        self.assertEqual(len(entries), 2)
        counts = {category: sum(main.form_category(entry) == category
                                for entry in self.catalog if entry.form)
                  for category in main.FORM_CATEGORIES}
        self.assertEqual(counts, {
            "Gigantamax": 34, "Mega": 97, "Regional": 59, "Other": 433,
        })
        self.assertEqual(len(main.filter_entries(self.catalog, False)), 1025)
        mega_only = main.filter_entries(self.catalog, True, {"Mega"})
        self.assertEqual(len(mega_only), 1025 + 97)
        self.assertIn(main.Entry(6, "Charizard", "Mega X"), mega_only)
        self.assertNotIn(main.Entry(6, "Charizard", "Gigantamax Form"), mega_only)

    def test_individual_other_form_selection(self):
        groups = main.other_form_groups(self.catalog)
        self.assertEqual(len(groups), 97)
        self.assertEqual(len(groups[869]), 63)  # Alcremie
        self.assertEqual(len(groups[201]), 28)  # Unown
        self.assertEqual(len(groups[386]), 4)   # Deoxys
        chosen = {(201, "!"), (386, "Attack Forme"),
                  (869, "Vanilla Cream Strawberry Sweet")}
        filtered = main.filter_entries(self.catalog, True, {"Other"}, chosen)
        self.assertEqual(len(filtered), 1025 + 3)
        self.assertIn(main.Entry(386, "Deoxys", "Attack Forme"), filtered)
        self.assertNotIn(main.Entry(386, "Deoxys", "Normal Forme"), filtered)
        self.assertNotIn(main.Entry(869, "Alcremie", "Gigantamax Form"), filtered)

    def test_sort_orders_and_sections(self):
        entries = self.read_lines([
            "Raichu (Alolan Form)", "Zubat", "Pikachu (Gigantamax Form)",
            "Abomasnow (Mega)", "Pikachu", "Raichu",
        ])
        self.assertEqual([entry.label for entry in entries], [
            "Pikachu", "Raichu", "Zubat", "Pikachu (Gigantamax Form)",
            "Raichu (Alolan Form)", "Abomasnow (Mega)",
        ])
        cases = [
            ("National Dex", False, [
                "Pikachu", "Pikachu (Gigantamax Form)", "Raichu",
                "Raichu (Alolan Form)", "Zubat", "Abomasnow (Mega)",
            ]),
            ("Alphabetical", True, [
                "Pikachu", "Raichu", "Zubat", "Abomasnow (Mega)",
                "Pikachu (Gigantamax Form)", "Raichu (Alolan Form)",
            ]),
            ("Alphabetical", False, [
                "Abomasnow (Mega)", "Pikachu", "Pikachu (Gigantamax Form)",
                "Raichu", "Raichu (Alolan Form)", "Zubat",
            ]),
        ]
        for order, separate, expected in cases:
            with self.subTest(order=order, separate=separate):
                self.assertEqual([entry.label for entry in main.sort_entries(
                    entries, order, separate)], expected)

    def test_generated_csv_is_one_name_per_line(self):
        selected = main.sort_entries(
            main.filter_entries(self.catalog, True, {"Gigantamax", "Regional"}),
            "National Dex", True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing_pokemon_custom.csv"
            main.write_editable_csv(path, selected)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1025 + 34 + 59)
            self.assertEqual(lines[0], "Bulbasaur")
            self.assertEqual(lines[1024], "Pecharunt")
            self.assertEqual(lines[1025], "Venusaur (Gigantamax Form)")
            self.assertEqual(main.read_names(path, self.lookup), selected)

    def test_generate_button_uses_master_and_selected_settings(self):
        app = main.App.__new__(main.App)
        app.include_forms = Mock()
        app.include_forms.get.return_value = True
        app.form_options = {category: Mock() for category in main.FORM_CATEGORIES}
        for category, option in app.form_options.items():
            option.get.return_value = category == "Mega"
        app.sort_order = Mock()
        app.sort_order.get.return_value = "Alphabetical"
        app.separate_forms = Mock()
        app.separate_forms.get.return_value = False
        app.csv_path = Mock()
        app.status = Mock()
        app.other_selected = {(201, "!")}
        app.other_label = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing_pokemon_mega.csv"
            with patch.object(main.filedialog, "asksaveasfilename", return_value=str(path)):
                app.generate_csv()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1025 + 97)
            self.assertEqual(lines[:2], ["Abomasnow", "Abomasnow (Mega)"])
            app.csv_path.set.assert_called_once_with(str(path))

    def test_pdf_contains_form_label(self):
        entries = self.read_lines(["Raichu (Alolan Form)", "Pikachu"])
        output = io.BytesIO()
        main.create_pdf(entries, output, main.PAGES["US Letter"])
        self.assertTrue(output.getvalue().startswith(b"%PDF-"))
        self.assertGreater(len(output.getvalue()), 1000)


if __name__ == "__main__":
    unittest.main()
