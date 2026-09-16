"""Offline tests for the Danish and English Gherkin desktop UI."""

import json
import io
import inspect
import queue
import threading
import tempfile
import time
import tkinter as tk
import unittest
import urllib.error
from functools import partial
from pathlib import Path
from tkinter import ttk
from unittest.mock import Mock, patch

from gherkin_gui import GherkinGui, fetch_models, load_settings, main, normalize_local_url, save_settings
from gherkin_story import OllamaError, generate_feature
from prompt_chains import PromptChain, PromptStage, load_chains, save_chains, standard_chain


class HeadlessStandardFlowTests(unittest.TestCase):
    def test_invalid_generated_feature_is_logged_after_worker_completion(self):
        """Catches a failed final GUI validation lacking a code-location record."""
        app = object.__new__(GherkinGui)
        app._closed = False
        app._results = queue.Queue()
        app._results.put(("generate", True, "private model output"))
        app._active_language = "en"
        app._last_stage = ""
        app._busy = True
        app.status_var = Mock()
        app.output_text = Mock()
        app.save_button = Mock()
        app.generate_button = Mock()
        app.connection_button = Mock()
        app.load_basis_button = Mock()
        app.chain_box = Mock()
        app.edit_chains_button = Mock()
        app.after = lambda *_: "next-poll"
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path):
                app._poll_results()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("validate_generated", content)
            self.assertIn("ValidationError", content)
            self.assertNotIn("private model output", content)
            app.output_text.insert.assert_not_called()

    def test_corrupt_chain_file_is_logged_without_changing_file(self):
        """Catches a load error shown in the GUI but absent from diagnostics."""
        app = object.__new__(GherkinGui)
        app.status_var = Mock()
        app._language_changed = lambda: None
        with tempfile.TemporaryDirectory() as directory:
            app.chain_path = Path(directory) / "chains.json"
            app.chain_path.write_text("{private invalid data", encoding="utf-8")
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path):
                app.reload_chains()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("load_chains", content)
            self.assertIn("PromptChainError", content)
            self.assertNotIn("private invalid data", content)
            self.assertEqual(app.chain_path.read_text(encoding="utf-8"), "{private invalid data")

    def test_story_file_read_failure_is_logged(self):
        """Catches direct GUI file errors that bypass the background worker."""
        app = object.__new__(GherkinGui)
        app.status_var = Mock()
        app.story_text = Mock()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "private-story.txt"
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path), patch(
                "gherkin_gui.filedialog.askopenfilename", return_value=str(missing),
            ):
                app.load_story_file()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("load_story", content)
            self.assertIn("FileNotFoundError", content)
            self.assertNotIn("private-story.txt", content)
            app.story_text.delete.assert_not_called()

    def test_settings_save_failure_is_logged(self):
        """Catches settings errors being visible only as a transient status line."""
        app = object.__new__(GherkinGui)
        app.status_var = Mock()
        app.url_var = Mock()
        app.url_var.get.return_value = "http://example.com"
        app.model_var = Mock()
        app.model_var.get.return_value = "mistral:latest"
        app.language_var = Mock()
        app.language_var.get.return_value = "en"
        with tempfile.TemporaryDirectory() as directory:
            app.settings_path = Path(directory) / "settings.json"
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path):
                app.save_current_settings()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("save_settings", content)
            self.assertIn("ValueError", content)
            self.assertFalse(app.settings_path.exists())

    def test_gui_startup_failure_is_logged_before_propagating(self):
        """Catches pythonw startup errors disappearing without a log entry."""
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path), patch(
                "gherkin_gui.GherkinGui", side_effect=RuntimeError("private startup detail"),
            ):
                with self.assertRaises(RuntimeError):
                    main()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("gui_startup", content)
            self.assertIn("RuntimeError", content)
            self.assertNotIn("private startup detail", content)

    def test_background_failure_logs_code_location_without_input_or_message(self):
        """Catches a GUI worker losing traceback context after queueing a short error."""
        app = object.__new__(GherkinGui)
        app._results = queue.Queue()
        app._busy = False
        app.generate_button = Mock()
        app.connection_button = Mock()
        app.load_basis_button = Mock()
        app.chain_box = Mock()
        app.edit_chains_button = Mock()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "gherkin-errors.log"

            def fail():
                raise OllamaError("private story token in server response")

            with patch("error_log.LOG_PATH", log_path):
                app._start_worker("generate", fail)
                operation, success, payload = app._results.get(timeout=2)
            self.assertEqual((operation, success), ("generate", False))
            self.assertIn("private story token", payload)
            self.assertTrue(log_path.exists(), "GUI-fejlen blev ikke logget")
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("generate", content)
            self.assertIn("OllamaError", content)
            self.assertIn("gherkin_gui.py:", content)
            self.assertNotIn("private story token", content)

    def test_invalid_edited_output_is_logged_before_save_dialog(self):
        """Catches synchronous save validation errors disappearing from diagnostics."""
        app = object.__new__(GherkinGui)
        app._output_language = "en"
        app.output_text = Mock()
        app.output_text.get.return_value = "private edited output"
        app.status_var = Mock()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path), patch(
                "gherkin_gui.filedialog.asksaveasfilename"
            ) as dialog:
                app.save_feature()
            dialog.assert_not_called()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("save_feature", content)
            self.assertIn("ValidationError", content)
            self.assertNotIn("private edited output", content)

    def test_unhandled_gui_callback_is_logged_without_private_message(self):
        """Catches a Tk callback exception vanishing in pythonw without context."""
        app = object.__new__(GherkinGui)
        app.status_var = Mock()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            try:
                raise RuntimeError("private token")
            except RuntimeError as error:
                self.assertTrue(hasattr(app, "report_callback_exception"))
                with patch("error_log.LOG_PATH", log_path):
                    app.report_callback_exception(RuntimeError, error, error.__traceback__)
            self.assertTrue(log_path.exists())
            self.assertIn("gui_callback", log_path.read_text(encoding="utf-8"))
            self.assertNotIn("private token", log_path.read_text(encoding="utf-8"))
            self.assertIn("log", app.status_var.set.call_args.args[0].lower())

    def test_standard_generation_forwards_raw_model_answer_to_stage_queue(self):
        """Catches the GUI omitting Standard model answers from intermediate results."""
        app = object.__new__(GherkinGui)
        feature = """# language: en
Feature: Welcome screen
  Scenario: Sign in
    Given a registered customer
    When the customer signs in
    Then the welcome screen is displayed
"""
        app._busy = False
        app.story_text = Mock()
        app.story_text.get.return_value = "A registered customer signs in"
        app.test_basis_text = Mock()
        app.test_basis_text.get.return_value = "Show the official application name"
        app.output_text = Mock()
        app.save_button = Mock()
        app.url_var = Mock()
        app.url_var.get.return_value = "http://localhost:11434"
        app.model_var = Mock()
        app.model_var.get.return_value = "mistral:latest"
        app.language_var = Mock()
        app.language_var.get.return_value = "en"
        app.chain_var = Mock()
        app.chain_var.get.return_value = "Standard"
        app.status_var = Mock()
        app._render_stage_outputs = lambda: None
        app._start_worker = lambda operation, work: app._results.put((operation, True, work()))

        generators = (
            partial(generate_feature, ask=lambda *_: feature),
            lambda *args, **kwargs: generate_feature(*args, ask=lambda *_: feature, **kwargs),
        )
        for generator in generators:
            with self.subTest(generator=generator):
                app._generator = generator
                app._results = queue.Queue()
                app.generate()

                queued = list(app._results.queue)
                self.assertIn(("stage", True, ("result", 1, "Standard", feature)), queued)
                self.assertEqual(queued[-1], ("generate", True, feature))


class SettingsTests(unittest.TestCase):
    def test_normalize_local_url_accepts_loopback(self):
        """Catches rejecting the default Ollama endpoint or keeping a trailing slash."""
        self.assertEqual(
            normalize_local_url("http://localhost:11434/"),
            "http://localhost:11434",
        )

    def test_normalize_local_url_rejects_nonlocal_or_ambiguous_addresses(self):
        """Catches sending a story to a remote or disguised endpoint."""
        for address in (
            "https://localhost:11434",
            "http://example.com:11434",
            "http://localhost.evil.test:11434",
            "http://user@localhost:11434",
            "http://localhost:11434/other",
            "http://localhost:11434?next=remote",
            "http://localhost:bad",
        ):
            with self.subTest(address=address), self.assertRaises(ValueError):
                normalize_local_url(address)

    def test_normalize_local_url_accepts_numeric_loopback(self):
        """Catches rejecting normal IPv4 and IPv6 local Ollama bindings."""
        self.assertEqual(
            normalize_local_url("http://127.0.0.1:11434"),
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            normalize_local_url("http://[::1]:11434"),
            "http://[::1]:11434",
        )

    def test_missing_settings_use_defaults_without_warning(self):
        """Catches startup failing before a settings file has been created."""
        with tempfile.TemporaryDirectory() as directory:
            settings, warning = load_settings(Path(directory) / "missing.json")
        self.assertEqual(
            settings,
            {"ollama_url": "http://localhost:11434", "model": "llama3.2", "language": "da"},
        )
        self.assertIsNone(warning)

    def test_saved_settings_are_loaded(self):
        """Catches forgetting the user's previously saved local model choice."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"ollama_url": "http://127.0.0.1:11434", "model": "phi3:latest"}),
                encoding="utf-8",
            )
            settings, warning = load_settings(path)
        self.assertEqual(settings["model"], "phi3:latest")
        self.assertEqual(settings["ollama_url"], "http://127.0.0.1:11434")
        self.assertIn("language", settings)
        self.assertEqual(settings["language"], "da")
        self.assertIsNone(warning)

    def test_english_setting_is_saved_and_loaded(self):
        """Catches losing the English choice between window sessions."""
        self.assertIn("language", inspect.signature(save_settings).parameters)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(path, "http://localhost:11434", "phi3:latest", language="en")
            settings, warning = load_settings(path)
        self.assertEqual(settings["language"], "en")
        self.assertIsNone(warning)

    def test_corrupt_settings_fall_back_with_warning(self):
        """Catches a bad settings file breaking window startup."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{broken", encoding="utf-8")
            settings, warning = load_settings(path)
        self.assertEqual(settings, {"ollama_url": "http://localhost:11434", "model": "llama3.2", "language": "da"})
        self.assertIsInstance(warning, str)

    def test_corrupt_settings_are_logged_without_file_contents(self):
        """Catches startup fallback concealing why settings could not be read."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"private token":', encoding="utf-8")
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path):
                settings, warning = load_settings(path)
            self.assertIsNotNone(warning)
            self.assertEqual(settings["language"], "da")
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("load_settings", content)
            self.assertIn("JSONDecodeError", content)
            self.assertNotIn("private token", content)

    def test_nonlocal_saved_url_is_not_used(self):
        """Catches a tampered settings file routing private stories remotely."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"ollama_url": "http://remote.test:11434", "model": "phi3"}),
                encoding="utf-8",
            )
            settings, warning = load_settings(path)
        self.assertEqual(settings["ollama_url"], "http://localhost:11434")
        self.assertIsInstance(warning, str)

    def test_save_settings_persists_only_local_endpoint_and_model(self):
        """Catches leaking story content or dropping the chosen model."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(path, "http://localhost:11434/", "phi3:latest")
            content = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(content, {"ollama_url": "http://localhost:11434", "model": "phi3:latest", "language": "da"})

    def test_save_settings_rejects_remote_endpoint_and_empty_model(self):
        """Catches persisting a setting that could leak a later story."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with self.assertRaises(ValueError):
                save_settings(path, "http://remote.test:11434", "llama3.2")
            with self.assertRaises(ValueError):
                save_settings(path, "http://localhost:11434", " ")
            self.assertFalse(path.exists())

    def test_failed_replace_keeps_old_settings_and_removes_temporary_file(self):
        """Catches partial settings loss if the final rename fails."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_bytes(b"old settings")
            with patch("gherkin_gui.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    save_settings(path, "http://localhost:11434", "phi3")
            self.assertEqual(path.read_bytes(), b"old settings")
            self.assertEqual([item.name for item in Path(directory).iterdir()], ["settings.json"])

    def test_fetch_models_reads_local_ollama_names(self):
        """Catches using the wrong endpoint or ignoring installed model names."""
        response = io.BytesIO(json.dumps({"models": [{"name": "llama3.2:latest"}, {"name": "phi3:latest"}]}).encode())
        with patch("gherkin_gui.urllib.request.urlopen", return_value=response) as request:
            names = fetch_models("http://localhost:11434/")
        self.assertEqual(names, ["llama3.2:latest", "phi3:latest"])
        self.assertEqual(request.call_args.args[0], "http://localhost:11434/api/tags")

    def test_fetch_models_handles_empty_list(self):
        """Catches treating an installation without models as a malformed response."""
        with patch("gherkin_gui.urllib.request.urlopen", return_value=io.BytesIO(b'{"models": []}')):
            self.assertEqual(fetch_models("http://localhost:11434"), [])

    def test_fetch_models_reports_connection_and_json_errors(self):
        """Catches raw network or decoding tracebacks in the window."""
        with patch("gherkin_gui.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(OllamaError):
                fetch_models("http://localhost:11434")
        with patch("gherkin_gui.urllib.request.urlopen", return_value=io.BytesIO(b"not-json")):
            with self.assertRaises(OllamaError):
                fetch_models("http://localhost:11434")

    def test_fetch_models_never_calls_remote_host(self):
        """Catches a bypass of loopback validation during model lookup."""
        with patch("gherkin_gui.urllib.request.urlopen") as request:
            with self.assertRaises(ValueError):
                fetch_models("http://remote.test:11434")
        request.assert_not_called()

    def test_cloud_models_are_not_offered_or_saved(self):
        """Catches local Ollama advertising a cloud-backed model for private stories."""
        response = io.BytesIO(json.dumps({"models": [
            {"name": "llama3.2:latest"}, {"name": "minimax-m2.5:cloud"}
        ]}).encode())
        with patch("gherkin_gui.urllib.request.urlopen", return_value=response):
            self.assertEqual(fetch_models("http://localhost:11434"), ["llama3.2:latest"])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                save_settings(Path(directory) / "settings.json", "http://localhost:11434", "minimax-m2.5:cloud")


class GuiTests(unittest.TestCase):
    VALID_FEATURE = """# language: da
Egenskab: Kontosaldo
  Scenarie: Se saldo
    Givet at brugeren er logget ind
    Når brugeren åbner kontosiden
    Så vises saldoen i DKK
"""
    ENGLISH_FEATURE = """# language: en
Feature: Account balance
  Scenario: View balance
    Given the user is signed in
    When the user opens the account page
    Then the balance is shown in DKK
"""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []

        def generator(story, model, url, language):
            self.calls.append((story, model, url, language))
            return ""

        self.app = GherkinGui(
            settings_path=Path(self.directory.name) / "settings.json",
            chain_path=Path(self.directory.name) / "chains.json",
            generator=generator,
            model_fetcher=lambda url: [],
        )
        self.app.withdraw()

    def tearDown(self):
        self.app.update_idletasks()
        self.app.close()
        self.directory.cleanup()

    def _pump_until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Vinduet behandlede ikke resultatet inden for tidsgrænsen.")

    def _chain(self, name="Min kæde", language="da"):
        return PromptChain(name, language, (
            PromptStage("Udkast", "System", "{{user_story}}"),
            PromptStage("Scenarier", "System", "{{previous_output}}"),
        ), "Ret {{invalid_output}} på grund af {{validation_error}}")

    def _install_chains(self, chains):
        save_chains(self.app.chain_path, chains)
        self.app.reload_chains()

    def test_chain_choices_follow_language_and_fall_back_to_standard(self):
        """Catches showing a chain in the wrong language or retaining an invalid selection."""
        self._install_chains([self._chain(), self._chain("English chain", "en")])
        self.assertEqual(tuple(self.app.chain_box["values"]), ("Standard", "Min kæde"))
        self.app.chain_var.set("Min kæde")
        self.app.language_var.set("en")
        self.assertEqual(tuple(self.app.chain_box["values"]), ("Standard", "English chain"))
        self.assertEqual(self.app.chain_var.get(), "Standard")

    def test_help_button_opens_readable_workflow_without_saving_data(self):
        """Catches the main help entry disappearing or hiding the copy-Standard guidance."""
        pending = [self.app]
        buttons = []
        while pending:
            widget = pending.pop()
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Hjælp":
                buttons.append(widget)
            pending.extend(widget.winfo_children())
        self.assertEqual(len(buttons), 1)
        buttons[0].invoke()
        windows = [child for child in self.app.winfo_children() if isinstance(child, tk.Toplevel)]
        self.assertEqual(len(windows), 1)
        self.assertIn("Hjælp", windows[0].title())
        pending = [windows[0]]
        visible_text = []
        while pending:
            widget = pending.pop()
            if isinstance(widget, tk.Text):
                visible_text.append(widget.get("1.0", "end-1c"))
                self.assertEqual(widget.cget("state"), "disabled")
            pending.extend(widget.winfo_children())
        guide = "\n".join(visible_text)
        for term in ("user story", "testbasis", "Standard", "Kopiér", "Gem kæde"):
            self.assertIn(term, guide)
        self.assertFalse(self.app.chain_path.exists())

    def test_action_buttons_share_width_and_right_edge_at_normal_and_minimum_size(self):
        """Catches the right-hand controls drifting or buttons changing width with label length."""
        try:
            for size in ("980x800", "720x640"):
                with self.subTest(size=size):
                    self.app.geometry(size)
                    self.app.deiconify()
                    self.app.update()
                    pending = [self.app]
                    buttons = {}
                    while pending:
                        widget = pending.pop()
                        if isinstance(widget, ttk.Button):
                            buttons[widget.cget("text")] = widget
                        pending.extend(widget.winfo_children())
                    self.assertEqual(len(buttons), 9)
                    self.assertEqual(len({button.winfo_width() for button in buttons.values()}), 1)
                    right_column = (
                        "Kontrollér forbindelse", "Gem indstillinger", "Hjælp",
                        "Redigér kæder", "Indlæs tekstfil", "Indlæs testbasis", "Gem .feature",
                    )
                    edges = [buttons[label].winfo_rootx() + buttons[label].winfo_width()
                             for label in right_column]
                    self.assertLessEqual(max(edges) - min(edges), 2)
                    for button in buttons.values():
                        self.assertGreaterEqual(button.winfo_rootx(), self.app.winfo_rootx())
                        self.assertLessEqual(
                            button.winfo_rootx() + button.winfo_width(),
                            self.app.winfo_rootx() + self.app.winfo_width(),
                        )
                        self.assertGreaterEqual(button.winfo_rooty(), self.app.winfo_rooty())
                        self.assertLessEqual(
                            button.winfo_rooty() + button.winfo_height(),
                            self.app.winfo_rooty() + self.app.winfo_height(),
                        )
        finally:
            self.app.withdraw()
            self.app.update()

    def test_help_close_button_matches_width_and_stays_visible_at_minimum_size(self):
        """Catches the help window clipping its close command when narrowed."""
        self.app.deiconify()
        self.app.update()
        self.app.help_button.invoke()
        window = next(child for child in self.app.winfo_children() if isinstance(child, tk.Toplevel))
        try:
            window.geometry("600x420")
            window.update()
            pending = [window]
            close_buttons = []
            while pending:
                widget = pending.pop()
                if isinstance(widget, ttk.Button) and widget.cget("text") == "Luk":
                    close_buttons.append(widget)
                pending.extend(widget.winfo_children())
            self.assertEqual(len(close_buttons), 1)
            close = close_buttons[0]
            self.assertEqual(close.winfo_width(), self.app.help_button.winfo_width())
            self.assertGreaterEqual(close.winfo_rootx(), window.winfo_rootx())
            self.assertLessEqual(close.winfo_rootx() + close.winfo_width(),
                                 window.winfo_rootx() + window.winfo_width())
            self.assertLessEqual(close.winfo_rooty() + close.winfo_height(),
                                 window.winfo_rooty() + window.winfo_height())
        finally:
            window.destroy()
            self.app.withdraw()
            self.app.update()

    def test_parent_close_cancel_keeps_editor_and_polling_alive(self):
        """Catches main-window destruction bypassing a dirty editor's Cancel choice."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Draft"))
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
            self.app.close()
        self.assertTrue(self.app.winfo_exists())
        self.assertTrue(editor.winfo_exists())
        self.assertFalse(self.app._closed)
        self.assertIn(self.app._poll_id, self.app.tk.call("after", "info"))
        editor.destroy()

    def test_parent_close_failed_editor_save_keeps_draft_and_polling_alive(self):
        """Catches failed Save on exit destroying the user's visible draft."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Draft"))
        editor.system_text.delete("1.0", "end")
        editor.system_text.insert("1.0", "Important unsaved prompt")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=True), patch(
            "prompt_chain_editor.save_chains", side_effect=OSError("locked")
        ):
            self.app.close()
        self.assertTrue(self.app.winfo_exists())
        self.assertTrue(editor.winfo_exists())
        self.assertFalse(self.app._closed)
        self.assertIn(self.app._poll_id, self.app.tk.call("after", "info"))
        self.assertEqual(editor.system_text.get("1.0", "end-1c"), "Important unsaved prompt")
        self.assertFalse(self.app.chain_path.exists())
        editor.destroy()

    def test_clean_language_change_updates_open_editor(self):
        """Catches a clean editor showing Danish chains after English is selected."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.app.language_var.set("en")
        self.assertTrue(editor.winfo_exists())
        self.assertEqual(editor.language, "en")
        self.assertEqual(editor.draft, standard_chain("en"))
        self.assertEqual(tuple(editor.chain_box["values"]), ("Standard",))
        editor.destroy()

    def test_dirty_language_change_cancel_restores_prior_selection_and_draft(self):
        """Catches Cancel leaving the main language at odds with the dirty editor."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Draft"))
        editor.system_text.delete("1.0", "end")
        editor.system_text.insert("1.0", "Keep this Danish draft")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
            self.app.language_var.set("en")
        self.assertEqual(self.app.language_var.get(), "da")
        self.assertEqual(editor.language, "da")
        self.assertEqual(editor.system_text.get("1.0", "end-1c"), "Keep this Danish draft")
        self.assertEqual(tuple(self.app.chain_box["values"]), ("Standard",))
        editor.destroy()

    def test_dirty_language_change_save_persists_old_language_and_updates_editor(self):
        """Catches Save switching editor language before persisting the original draft."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Danish custom"))
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=True):
            self.app.language_var.set("en")
        self.assertEqual([(chain.name, chain.language) for chain in load_chains(self.app.chain_path)],
                         [("Danish custom", "da")])
        self.assertEqual(self.app.language_var.get(), "en")
        self.assertEqual(editor.language, "en")
        self.assertEqual(editor.draft, standard_chain("en"))
        editor.destroy()

    def test_dirty_language_change_discard_does_not_persist_draft(self):
        """Catches Discard carrying Danish edits into the English editor."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Danish custom"))
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=False):
            self.app.language_var.set("en")
        self.assertFalse(self.app.chain_path.exists())
        self.assertEqual(editor.language, "en")
        self.assertEqual(editor.draft, standard_chain("en"))
        editor.destroy()

    def test_dirty_language_change_failed_save_restores_prior_language(self):
        """Catches a storage failure switching languages while the draft remains unsaved."""
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Danish custom"))
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=True), patch(
            "prompt_chain_editor.save_chains", side_effect=OSError("locked")
        ):
            self.app.language_var.set("en")
        self.assertEqual(self.app.language_var.get(), "da")
        self.assertEqual(editor.language, "da")
        self.assertEqual(editor.draft.name, "Danish custom")
        self.assertTrue(editor.dirty)
        editor.destroy()

    def test_custom_standard_json_is_not_offered_as_duplicate_gui_choice(self):
        """Catches a reserved-name JSON entry creating two Standard picker choices."""
        self.app.chain_path.write_text(json.dumps({"version": 1, "chains": [{
            "name": "Standard", "language": "da",
            "stages": [{"name": "Draft", "system_prompt": "Rules", "user_prompt": "{{user_story}}"}],
            "repair_prompt": "Repair",
        }]}), encoding="utf-8")
        self.app.reload_chains()
        self.assertEqual(tuple(self.app.chain_box["values"]), ("Standard",))
        self.assertIn("kædefil", self.app.status_var.get().lower())

    def test_selected_chain_and_inputs_are_snapshotted(self):
        """Catches a worker seeing a later chain or basis edit instead of the chosen profile."""
        self._install_chains([self._chain(), self._chain("Anden")])
        entered, release = threading.Event(), threading.Event()
        seen = []

        def generate(story, model, url, language, test_basis, *, chain, on_stage):
            seen.append((story, test_basis, chain))
            entered.set()
            release.wait(2)
            return self.VALID_FEATURE

        self.app._generator = generate
        self.app.story_text.insert("1.0", "Som kunde vil jeg se saldo")
        self.app.test_basis_text.insert("1.0", "Advar ved minus")
        self.app.chain_var.set("Min kæde")
        self.app.generate()
        self.assertTrue(entered.wait(1))
        self.app.chain_var.set("Anden")
        self.app.test_basis_text.insert("end", " senere")
        self.assertEqual((seen[0][0], seen[0][1], seen[0][2].name),
                         ("Som kunde vil jeg se saldo", "Advar ved minus", "Min kæde"))
        self.assertIsInstance(seen[0][2].stages, tuple)
        release.set()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))

    def test_default_chain_never_passes_new_generator_kwargs(self):
        """Catches breaking older story-only generators on the standard path."""
        self._install_chains([self._chain()])
        self.app._generator = lambda story, model, url, language: self.VALID_FEATURE
        self.app.story_text.insert("1.0", "Som kunde vil jeg se saldo")
        self.app.generate()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))

    def test_stage_events_keep_busy_and_intermediate_output_unsavable(self):
        """Catches stage progress ending busy state or leaking draft text into .feature."""
        self._install_chains([self._chain()])
        self.app.chain_var.set("Min kæde")
        self.app.story_text.insert("1.0", "En story")
        release = threading.Event()

        def generate(story, model, url, language, *, chain, on_stage):
            on_stage("start", 1, "Udkast", "")
            on_stage("result", 1, "Udkast", "fortroligt mellemresultat")
            on_stage("start", 2, "Scenarier", "")
            release.wait(2)
            return self.VALID_FEATURE

        self.app._generator = generate
        self.app.generate()
        self._pump_until(lambda: "Scenarier" in self.app.status_var.get())
        self.assertTrue(self.app._busy)
        self.assertTrue(self.app.generate_button.instate(["disabled"]))
        self.assertTrue(self.app.chain_box.instate(["disabled"]))
        self.assertTrue(self.app.save_button.instate(["disabled"]))
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), "")
        self.app.show_stage_outputs()
        self.assertIn("fortroligt mellemresultat", self.app.stage_output_text.get("1.0", "end-1c"))
        with patch("gherkin_gui.filedialog.asksaveasfilename") as dialog:
            self.app.save_feature()
        dialog.assert_not_called()
        release.set()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), self.VALID_FEATURE)

    def test_failed_named_stage_and_invalid_final_leave_no_savable_feature(self):
        """Catches failure detail disappearing or an invalid final draft being accepted."""
        self._install_chains([self._chain()])
        self.app.chain_var.set("Min kæde")
        self.app.story_text.insert("1.0", "En story")

        def fail(story, model, url, language, *, chain, on_stage):
            on_stage("start", 2, "Scenarier", "")
            raise OllamaError("offline")

        self.app._generator = fail
        self.app.generate()
        self._pump_until(lambda: "offline" in self.app.status_var.get())
        self.assertIn("Scenarier", self.app.status_var.get())
        self.assertTrue(self.app.save_button.instate(["disabled"]))
        self.app._generator = lambda story, model, url, language, *, chain, on_stage: (
            on_stage("result", 2, "Scenarier", "ikke Gherkin") or "ikke Gherkin"
        )
        self.app.generate()
        self._pump_until(lambda: "ugyldig" in self.app.status_var.get().lower())
        self.assertTrue(self.app.save_button.instate(["disabled"]))
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), "")

    def test_editor_save_refreshes_chain_choices_without_changing_settings_schema(self):
        """Catches editor saves not reaching the picker or persisting chain selection in settings."""
        self.app.save_current_settings()
        self.app.edit_chains()
        editor = self.app.chain_editor
        self.assertTrue(editor.copy_standard_chain("Min kæde"))
        self.assertTrue(editor.save_chain())
        self.assertIn("Min kæde", self.app.chain_box["values"])
        self.assertEqual(self.app.chain_var.get(), "Min kæde")
        self.app.save_current_settings()
        self.assertEqual(set(json.loads(self.app.settings_path.read_text(encoding="utf-8"))),
                         {"ollama_url", "model", "language"})
        editor.close()

    def test_corrupt_chain_file_warns_and_offers_only_standard(self):
        """Catches corrupt user data crashing the window or silently discarding it."""
        self.app.chain_path.write_text("{broken", encoding="utf-8")
        self.app.reload_chains()
        self.assertEqual(tuple(self.app.chain_box["values"]), ("Standard",))
        self.assertIn("kædefil", self.app.status_var.get().lower())
        self.assertEqual(self.app.chain_path.read_text(encoding="utf-8"), "{broken")

    def test_blank_story_does_not_start_generation(self):
        """Catches sending an empty story to the local model."""
        self.app.story_text.insert("1.0", "   ")
        self.app.generate()
        self.assertEqual(self.calls, [])
        self.assertIn("tom", self.app.status_var.get().lower())

    def test_valid_generation_shows_feature_and_enables_save(self):
        """Catches hiding valid Gherkin or leaving save disabled after success."""
        self.app._generator = lambda story, model, url, language: self.VALID_FEATURE
        self.app.story_text.insert("1.0", "Som bruger vil jeg se saldo")
        self.app.generate()
        self.assertTrue(self.app.generate_button.instate(["disabled"]))
        self._pump_until(lambda: self.app.output_text.get("1.0", "end-1c") == self.VALID_FEATURE)
        self.assertTrue(self.app.save_button.instate(["!disabled"]))
        self.assertIn("valideret", self.app.status_var.get().lower())

    def test_blank_basis_keeps_legacy_generator_call(self):
        """Catches passing an unnecessary keyword to story-only generators."""
        self.app._generator = lambda story, model, url, language: self.VALID_FEATURE
        self.app.story_text.insert("1.0", "Som bruger vil jeg se saldo")
        self.app.generate()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), self.VALID_FEATURE)

    def test_typed_basis_is_a_separate_generator_argument_snapshot(self):
        """Catches dropping the basis or merging it into the story on a worker thread."""
        entered, release = threading.Event(), threading.Event()
        seen = []

        def generate(story, model, url, language, test_basis=""):
            seen.append((story, test_basis))
            entered.set()
            release.wait(2)
            return self.VALID_FEATURE

        self.app._generator = generate
        self.app.story_text.insert("1.0", "Som kunde vil jeg se saldo")
        self.app.test_basis_text.insert("1.0", "Saldo vises i DKK")
        self.app.generate()
        self.assertTrue(entered.wait(1))
        self.app.test_basis_text.insert("end", "\nÆndret senere")
        self.assertEqual(seen, [("Som kunde vil jeg se saldo", "Saldo vises i DKK")])
        release.set()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))

    def test_load_basis_text_file_remains_editable(self):
        """Catches failing to show actual extracted text or making it read-only."""
        basis_path = Path(self.directory.name) / "krav.md"
        basis_path.write_text("Saldo vises i DKK", encoding="utf-8")
        self.app.test_basis_text.insert("1.0", "Tidligere kriterium")
        with patch("gherkin_gui.filedialog.askopenfilename", return_value=str(basis_path)):
            self.app.load_test_basis_file()
        self._pump_until(lambda: self.app.test_basis_text.get("1.0", "end-1c") == "Saldo vises i DKK")
        self.assertNotIn("Tidligere kriterium", self.app.test_basis_text.get("1.0", "end-1c"))
        self.app.test_basis_text.insert("end", "\nOg i EUR")
        self.assertIn("Og i EUR", self.app.test_basis_text.get("1.0", "end-1c"))

    def test_empty_word_table_preserves_previous_basis(self):
        """Catches a visually empty Word table replacing edited basis with a separator."""
        from docx import Document

        basis_path = Path(self.directory.name) / "empty-table.docx"
        document = Document()
        document.add_table(rows=1, cols=2)
        document.save(basis_path)
        self.app.test_basis_text.insert("1.0", "Bevar dette kriterium")

        with patch("gherkin_gui.filedialog.askopenfilename", return_value=str(basis_path)):
            self.app.load_test_basis_file()
        self._pump_until(lambda: not self.app._busy)

        self.assertIn("mislykkedes", self.app.status_var.get().lower())
        self.assertEqual(self.app.test_basis_text.get("1.0", "end-1c"), "Bevar dette kriterium")

    def test_bad_pdf_or_word_preserves_previous_basis(self):
        """Catches erasing manually edited basis when document extraction fails."""
        from pypdf import PdfWriter

        self.app.test_basis_text.insert("1.0", "Bevar dette kriterium")
        for suffix in (".pdf", ".docx"):
            with self.subTest(suffix=suffix):
                invalid_path = Path(self.directory.name) / ("korrupt" + suffix)
                if suffix == ".pdf":
                    writer = PdfWriter()
                    writer.add_blank_page(width=72, height=72)
                    with invalid_path.open("wb") as stream:
                        writer.write(stream)
                else:
                    invalid_path.write_bytes(b"not a document")
                with patch("gherkin_gui.filedialog.askopenfilename", return_value=str(invalid_path)):
                    self.app.load_test_basis_file()
                self._pump_until(lambda: "mislykkedes" in self.app.status_var.get().lower())
                self.assertEqual(self.app.test_basis_text.get("1.0", "end-1c"), "Bevar dette kriterium")
                self.assertFalse(self.app._busy)
                self.app.status_var.set("Klar")

    def test_basis_and_story_are_not_saved_in_settings(self):
        """Catches leaking confidential source content to the settings JSON."""
        self.app.story_text.insert("1.0", "Fortrolig story")
        self.app.test_basis_text.insert("1.0", "Fortrolige acceptkriterier")
        self.app.save_current_settings()
        content = json.loads(self.app.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(set(content), {"ollama_url", "model", "language"})
        self.assertNotIn("Fortrolig", self.app.settings_path.read_text(encoding="utf-8"))

    def test_english_selection_generates_savable_english_feature(self):
        """Catches the window ignoring English selection or revalidating as Danish."""
        self.assertTrue(hasattr(self.app, "language_var"))
        self.app.language_var.set("en")
        chosen = []

        def generate(story, model, url, language):
            chosen.append(language)
            return self.ENGLISH_FEATURE

        self.app._generator = generate
        self.app.story_text.insert("1.0", "Show my balance")
        self.app.generate()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))
        self.assertEqual(chosen, ["en"])
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), self.ENGLISH_FEATURE)

    def test_generated_english_stays_savable_after_selection_changes(self):
        """Catches saving against the newly selected language instead of the result language."""
        self.assertTrue(hasattr(self.app, "language_var"))
        self.app.language_var.set("en")
        self.app._generator = lambda story, model, url, language: self.ENGLISH_FEATURE
        self.app.story_text.insert("1.0", "Show my balance")
        self.app.generate()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))
        self.app.language_var.set("da")
        destination = Path(self.directory.name) / "english.feature"
        with patch("gherkin_gui.filedialog.asksaveasfilename", return_value=str(destination)):
            self.app.save_feature()
        self.assertEqual(destination.read_text(encoding="utf-8"), self.ENGLISH_FEATURE)

    def test_duplicate_generate_is_ignored_while_worker_runs(self):
        """Catches two model requests from impatient repeated clicks."""
        entered, release = threading.Event(), threading.Event()

        def generate(story, model, url, language):
            self.calls.append(story)
            entered.set()
            release.wait(2)
            return self.VALID_FEATURE

        self.app._generator = generate
        self.app.story_text.insert("1.0", "En story")
        self.app.generate()
        self.assertTrue(entered.wait(1))
        self.app.generate()
        self.assertEqual(self.calls, ["En story"])
        release.set()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))

    def test_failed_generation_leaves_no_savable_output(self):
        """Catches stale valid output being saved after a failed retry."""
        self.app._generator = lambda *_, **__: self.VALID_FEATURE
        self.app.story_text.insert("1.0", "En story")
        self.app.generate()
        self._pump_until(lambda: self.app.save_button.instate(["!disabled"]))

        def fail(*_, **__):
            raise OllamaError("offline")

        self.app._generator = fail
        self.app.generate()
        self._pump_until(lambda: "offline" in self.app.status_var.get())
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), "")
        self.assertTrue(self.app.save_button.instate(["disabled"]))

    def test_invalid_generation_is_rejected_by_real_validator(self):
        """Catches showing malformed model output as ready-to-save Gherkin."""
        self.app._generator = lambda *_, **__: "Egenskab: Uden sprogmarkør"
        self.app.story_text.insert("1.0", "En story")
        self.app.generate()
        self._pump_until(lambda: "ugyldig" in self.app.status_var.get().lower())
        self.assertTrue(self.app.save_button.instate(["disabled"]))
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), "")

    def test_cloud_model_cannot_be_sent_to_ollama(self):
        """Catches bypassing the picker by typing a cloud model name."""
        self.app.story_text.insert("1.0", "En privat story")
        self.app.model_var.set("minimax-m2.5:cloud")
        self.app.generate()
        self.assertEqual(self.calls, [])
        self.assertIn("cloud", self.app.status_var.get().lower())

    def test_connection_updates_models_without_changing_selection(self):
        """Catches losing the user's model choice while refreshing local models."""
        self.app._model_fetcher = lambda url: ["llama3.2:latest", "phi3:latest"]
        self.app.check_connection()
        self._pump_until(lambda: len(self.app.model_box["values"]) == 2)
        self.assertEqual(self.app.model_var.get(), "llama3.2")
        self.assertIn("2", self.app.status_var.get())

    def test_connection_failure_is_visible_without_model_change(self):
        """Catches an unavailable Ollama server silently disabling the app."""
        def fail(url):
            raise OllamaError("offline")

        self.app._model_fetcher = fail
        self.app.check_connection()
        self._pump_until(lambda: "offline" in self.app.status_var.get())
        self.assertEqual(self.app.model_var.get(), "llama3.2")

    def test_save_settings_button_persists_choice(self):
        """Catches UI settings not surviving a restart."""
        self.app.model_var.set("phi3:latest")
        self.app.save_current_settings()
        content = json.loads(self.app.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(content["model"], "phi3:latest")

    def test_save_settings_button_persists_english_selection(self):
        """Catches displaying English without saving that choice for restart."""
        self.assertTrue(hasattr(self.app, "language_var"))
        self.app.language_var.set("en")
        self.app.save_current_settings()
        content = json.loads(self.app.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(content["language"], "en")

    def test_load_story_file_reads_utf8(self):
        """Catches broken Danish characters when opening a story file."""
        story_path = Path(self.directory.name) / "story.txt"
        story_path.write_text("Som bruger ønsker jeg adgang", encoding="utf-8")
        with patch("gherkin_gui.filedialog.askopenfilename", return_value=str(story_path)):
            self.app.load_story_file()
        self.assertEqual(self.app.story_text.get("1.0", "end-1c"), "Som bruger ønsker jeg adgang")

    def test_save_feature_validates_edited_output_before_writing(self):
        """Catches an edited malformed feature replacing an existing file."""
        destination = Path(self.directory.name) / "result.feature"
        destination.write_bytes(b"old feature")
        self.app.output_text.insert("1.0", self.VALID_FEATURE)
        with patch("gherkin_gui.filedialog.asksaveasfilename", return_value=str(destination)):
            self.app.save_feature()
        self.assertEqual(destination.read_text(encoding="utf-8"), self.VALID_FEATURE)
        self.app.output_text.delete("1.0", "end")
        self.app.output_text.insert("1.0", "broken")
        with patch("gherkin_gui.filedialog.asksaveasfilename", return_value=str(destination)):
            self.app.save_feature()
        self.assertEqual(destination.read_text(encoding="utf-8"), self.VALID_FEATURE)


if __name__ == "__main__":
    unittest.main()
