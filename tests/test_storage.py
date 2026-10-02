import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from genius_kitchen.inventory import Inventory
from genius_kitchen.models import Ingredient
from genius_kitchen.storage import JSONInventoryStore


class JSONInventoryStoreTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.directory = Path(scratch.name)
        self.store = JSONInventoryStore(self.directory / "inventory.json")
        self.original = Inventory([Ingredient("Milk", 1.5, "litre", date(2028, 2, 29))])
        self.replacement = Inventory([Ingredient("Rice", 2, "kg", date(2029, 1, 1))])

    def test_missing_inventory_is_empty_without_creating_files(self):
        self.assertEqual(self.store.load().ingredients, ())
        self.assertFalse(self.store.path.exists())
        self.assertEqual(tuple(self.directory.iterdir()), ())

    def test_roundtrip_preserves_all_fields_including_unicode(self):
        self.original.add(Ingredient("ข้าว", 2.25, "kg", date(2029, 1, 1), "Pantry"))
        self.store.save(self.original)
        self.assertEqual(self.store.load().ingredients, self.original.ingredients)
        saved = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertIsInstance(saved, list)
        self.assertEqual(saved, [item.to_dict() for item in self.original.ingredients])

    def test_save_creates_parent_directories_and_can_replace_with_empty_inventory(self):
        store = JSONInventoryStore(self.directory / "nested" / "pantry" / "inventory.json")
        store.save(self.original)
        self.assertEqual(store.load().ingredients, self.original.ingredients)
        store.save(Inventory())
        self.assertEqual(store.load().ingredients, ())
        self.assertEqual(json.loads(store.path.read_text(encoding="utf-8")), [])

    def test_malformed_data_reports_file_and_preserves_original_bytes(self):
        for content in (b"{", b"null", b"{}", b'"text"', b"[{}]", b"[3]", b"\xff"):
            with self.subTest(content=content):
                self.store.path.write_bytes(content)
                with self.assertRaisesRegex(ValueError, "inventory.json"):
                    self.store.load()
                self.assertEqual(self.store.path.read_bytes(), content)

    def test_invalid_second_record_reports_item_and_field(self):
        valid = self.original.ingredients[0].to_dict()
        content = json.dumps([valid, {**valid, "quantity": True}]).encode("utf-8")
        self.store.path.write_bytes(content)
        with self.assertRaisesRegex(ValueError, "inventory.json, item 2: Quantity"):
            self.store.load()
        self.assertEqual(self.store.path.read_bytes(), content)

    def test_read_permission_failure_is_not_treated_as_first_run(self):
        self.store.save(self.original)
        before = self.store.path.read_bytes()
        with patch.object(Path, "read_text", side_effect=PermissionError("denied read")):
            with self.assertRaises(PermissionError):
                self.store.load()
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_failed_directory_creation_preserves_saved_inventory(self):
        self.store.save(self.original)
        before = self.store.path.read_bytes()
        with patch.object(Path, "mkdir", side_effect=PermissionError("denied directory access")):
            with self.assertRaises(PermissionError):
                self.store.save(self.replacement)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_partial_temporary_write_failure_preserves_saved_inventory(self):
        self.store.save(self.original)
        before = self.store.path.read_bytes()
        temporary = self.store.path.with_suffix(".json.tmp")

        def fail_during_write(*args, **kwargs):
            temporary.write_bytes(b'[{"name":')
            raise OSError("disk full during temporary write")

        with patch.object(Path, "write_text", side_effect=fail_during_write):
            with self.assertRaises(OSError):
                self.store.save(self.replacement)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.load().ingredients, self.original.ingredients)

    def test_failed_replace_preserves_original_and_a_later_retry_succeeds(self):
        self.store.save(self.original)
        before = self.store.path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                self.store.save(self.replacement)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.save(self.replacement)
        self.assertEqual(self.store.load().ingredients, self.replacement.ingredients)

    def test_serialization_failure_happens_before_any_disk_write(self):
        self.store.save(self.original)
        before = self.store.path.read_bytes()
        with (
            patch.object(Ingredient, "to_dict", return_value={"quantity": float("nan")}),
            patch.object(Path, "mkdir") as mkdir,
            patch.object(Path, "write_text") as write,
            patch.object(Path, "replace") as replace,
        ):
            with self.assertRaises(ValueError):
                self.store.save(self.replacement)
            mkdir.assert_not_called()
            write.assert_not_called()
            replace.assert_not_called()
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
