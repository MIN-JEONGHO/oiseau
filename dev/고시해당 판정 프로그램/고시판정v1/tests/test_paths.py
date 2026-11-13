import unittest

import paths


class PathsTest(unittest.TestCase):
    def test_resource_paths_are_under_asset_root(self):
        root = paths.asset_root()
        self.assertTrue(paths.notices_root().is_relative_to(root))
        self.assertTrue(paths.threshold_table_path().is_relative_to(root))
        self.assertTrue(paths.ui_root().is_relative_to(root))
        self.assertEqual(paths.resource_path("a", "b"), root / "resources" / "a" / "b")

    def test_source_run_is_not_frozen(self):
        self.assertFalse(paths.is_frozen())


if __name__ == "__main__":
    unittest.main()
