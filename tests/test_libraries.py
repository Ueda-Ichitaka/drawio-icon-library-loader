"""Tests for drawio_libs.libraries: library ids, name stems, discovery and format de-duplication."""

import os
import tempfile
import unittest

from drawio_libs.libraries import DEFAULT_PREFER, discover, library_id, library_stem


class LibraryIdTest(unittest.TestCase):
    def test_id_is_service_prefix_plus_encoded_path(self):
        self.assertEqual(library_id("/home/u/My Lib.xml"), "S%2Fhome%2Fu%2FMy%20Lib.xml")

    def test_id_encodes_non_ascii_as_utf8(self):
        self.assertEqual(library_id("/a/café.xml"), "S%2Fa%2Fcaf%C3%A9.xml")

    def test_id_keeps_the_characters_encode_uri_component_keeps(self):
        self.assertEqual(library_id("/a-_.!~*'()"), "S%2Fa-_.!~*'()")

    def test_id_encodes_semicolon_so_it_cannot_split_the_clibs_list(self):
        self.assertEqual(library_id("/a;b.xml"), "S%2Fa%3Bb.xml")


class LibraryStemTest(unittest.TestCase):
    def test_strips_a_single_known_extension(self):
        for name in ("A.xml", "A.drawio", "A.drawiolib"):
            self.assertEqual(library_stem(name, DEFAULT_PREFER), "A", name)

    def test_strips_stacked_extensions(self):
        self.assertEqual(library_stem("Labs 2026.drawio.xml", DEFAULT_PREFER), "Labs 2026")

    def test_only_strips_at_the_end(self):
        self.assertEqual(library_stem("a.xml.backup.xml", DEFAULT_PREFER), "a.xml.backup")

    def test_unknown_extension_is_not_a_library(self):
        self.assertIsNone(library_stem("README.md", DEFAULT_PREFER))
        self.assertIsNone(library_stem("noextension", DEFAULT_PREFER))

    def test_extension_match_is_case_insensitive(self):
        self.assertEqual(library_stem("A.XML", DEFAULT_PREFER), "A")


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def touch(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("<mxlibrary>[]</mxlibrary>")
        return path

    def paths(self, result):
        return [lib.path for lib in result.libraries]

    def test_explicit_file_is_loaded(self):
        lib = self.touch("A.xml")
        result = discover([lib], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [lib])
        self.assertEqual(result.warnings, [])

    def test_missing_entry_is_skipped_with_a_warning(self):
        missing = os.path.join(self.root, "gone.xml")
        result = discover([missing], DEFAULT_PREFER)
        self.assertEqual(result.libraries, [])
        self.assertEqual(len(result.warnings), 1)
        self.assertIn(missing, result.warnings[0])

    def test_directory_loads_every_library_file_sorted_case_insensitively(self):
        b = self.touch("lib", "b.xml")
        a = self.touch("lib", "A.xml")
        self.touch("lib", "README.md")
        result = discover([os.path.join(self.root, "lib")], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [a, b])

    def test_directory_skips_hidden_files_and_subdirectories(self):
        keep = self.touch("lib", "keep.xml")
        self.touch("lib", ".hidden.xml")
        self.touch("lib", "sub", "nested.xml")
        result = discover([os.path.join(self.root, "lib")], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [keep])

    def test_directory_loads_a_library_present_in_two_formats_once(self):
        xml = self.touch("lib", "Cyber.xml")
        self.touch("lib", "Cyber.drawio")
        result = discover([os.path.join(self.root, "lib")], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [xml])

    def test_prefer_order_decides_which_format_wins(self):
        self.touch("lib", "Cyber.xml")
        drawio = self.touch("lib", "Cyber.drawio")
        result = discover([os.path.join(self.root, "lib")], [".drawio", ".xml"])
        self.assertEqual(self.paths(result), [drawio])

    def test_double_extension_counts_as_the_same_library(self):
        self.touch("lib", "Labs.drawio.xml")
        winner = self.touch("lib", "Labs.drawio")
        result = discover([os.path.join(self.root, "lib")], [".drawio", ".xml"])
        self.assertEqual(self.paths(result), [winner])

    def test_extensions_outside_prefer_are_ignored_in_directories(self):
        xml = self.touch("lib", "a.xml")
        self.touch("lib", "b.drawio")
        result = discover([os.path.join(self.root, "lib")], [".xml"])
        self.assertEqual(self.paths(result), [xml])

    def test_explicit_files_are_never_de_duplicated_by_stem(self):
        xml = self.touch("A.xml")
        drawio = self.touch("A.drawio")
        result = discover([xml, drawio], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [xml, drawio])

    def test_same_file_named_twice_is_loaded_once(self):
        lib = self.touch("A.xml")
        result = discover([lib, os.path.join(self.root, ".", "A.xml")], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [lib])

    def test_entry_order_is_kept(self):
        first = self.touch("z.xml")
        second = self.touch("a.xml")
        result = discover([first, second], DEFAULT_PREFER)
        self.assertEqual(self.paths(result), [first, second])

    def test_library_exposes_its_draw_io_id(self):
        lib = self.touch("My Lib.xml")
        result = discover([lib], DEFAULT_PREFER)
        self.assertEqual(result.libraries[0].id, library_id(lib))


if __name__ == "__main__":
    unittest.main()
