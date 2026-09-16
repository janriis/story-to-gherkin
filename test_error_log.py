"""Tests for the local, privacy-conscious diagnostic log."""

import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


class ErrorLogTests(unittest.TestCase):
    def test_log_records_operation_type_and_code_location_without_private_text(self):
        self.assertIsNotNone(importlib.util.find_spec("error_log"))
        log_error = importlib.import_module("error_log").log_error

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "gherkin-errors.log"
            try:
                raise ValueError("private story and model output")
            except ValueError as error:
                log_error("generate", error, path=path)

            content = path.read_text(encoding="utf-8")
            self.assertIn("generate", content)
            self.assertIn("ValueError", content)
            self.assertIn("test_error_log.py:", content)
            self.assertNotIn("private story", content)
            self.assertNotIn("model output", content)

    def test_chained_errors_show_root_type_without_exception_messages(self):
        self.assertIsNotNone(importlib.util.find_spec("error_log"))
        log_error = importlib.import_module("error_log").log_error

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gherkin-errors.log"
            try:
                try:
                    raise OSError("private document path")
                except OSError as cause:
                    raise RuntimeError("private prompt") from cause
            except RuntimeError as error:
                log_error("load_basis", error, path=path)

            content = path.read_text(encoding="utf-8")
            self.assertIn("RuntimeError", content)
            self.assertIn("OSError", content)
            self.assertNotIn("private document path", content)
            self.assertNotIn("private prompt", content)

    def test_log_rotates_and_logging_failure_does_not_replace_original_error(self):
        self.assertIsNotNone(importlib.util.find_spec("error_log"))
        log_error = importlib.import_module("error_log").log_error

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "gherkin-errors.log"
            for _ in range(12):
                try:
                    raise ValueError("private")
                except ValueError as error:
                    log_error("generate", error, path=path, max_bytes=180, backup_count=2)
            self.assertTrue(path.exists())
            self.assertTrue(path.with_name("gherkin-errors.log.1").exists())
            self.assertFalse(path.with_name("gherkin-errors.log.3").exists())

            blocked = Path(directory) / "not-a-directory"
            blocked.write_text("unchanged", encoding="utf-8")
            log_error("generate", ValueError("private"), path=blocked / "file.log")
            self.assertEqual(blocked.read_text(encoding="utf-8"), "unchanged")


if __name__ == "__main__":
    unittest.main()
