"""GUI contract tests for the local prompt-chain editor."""

import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import ttk
from unittest.mock import Mock, patch

from prompt_chains import PromptChain, PromptStage, load_chains, save_chains, standard_chain
from prompt_chain_editor import PromptChainEditor


class HeadlessEditorErrorTests(unittest.TestCase):
    def test_editor_chain_load_failure_is_logged_before_warning(self):
        """Catches a newly corrupt chain file being shown but not diagnosed."""
        from prompt_chains import PromptChainError

        class StopAfterWarning(Exception):
            pass

        with TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path), patch(
                "prompt_chain_editor.tk.Toplevel.__init__", return_value=None,
            ), patch(
                "prompt_chain_editor.load_chains", side_effect=PromptChainError("private prompt"),
            ), patch(
                "prompt_chain_editor.messagebox.showwarning", side_effect=StopAfterWarning,
            ):
                with self.assertRaises(StopAfterWarning):
                    PromptChainEditor(None, Path(directory) / "chains.json", "da", lambda _: None)
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("editor_load_chains", content)
            self.assertIn("PromptChainError", content)
            self.assertNotIn("private prompt", content)

    def test_invalid_chain_save_logs_failure_without_chain_contents(self):
        """Catches editor validation errors losing their technical location."""
        editor = object.__new__(PromptChainEditor)
        editor._pending_delete_name = None
        editor._origin_name = "My chain"
        editor._load_error = None
        editor._sync_texts = lambda: None
        editor.saved_chains = []
        editor.language = "da"
        editor.draft = PromptChain("My chain", "da", (), "private prompt text")
        editor.status_var = Mock()
        with TemporaryDirectory() as directory:
            editor.path = Path(directory) / "chains.json"
            log_path = Path(directory) / "logs" / "gherkin-errors.log"
            with patch("error_log.LOG_PATH", log_path):
                self.assertFalse(editor.save_chain())
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("save_chain", content)
            self.assertIn("PromptChainError", content)
            self.assertNotIn("private prompt text", content)


class PromptChainEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "chains.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self._close_root)
        self.saved = []
        self.editor = PromptChainEditor(self.root, self.path, "da", self.saved.append)
        self.editor.withdraw()

    def _close_root(self):
        self.root.update()
        self.root.destroy()

    def button(self, label):
        """Find a visible editor command so tests exercise its real callback."""
        pending = [self.editor]
        while pending:
            widget = pending.pop()
            if isinstance(widget, ttk.Button) and widget.cget("text") == label:
                return widget
            pending.extend(widget.winfo_children())
        self.fail(f"Missing button: {label}")

    def test_copy_standard_then_add_and_move_stage(self):
        """Catches a stage-order edit being lost from the draft."""
        self.editor.copy_standard_chain("Min kæde")
        self.editor.add_stage("Analyse")
        self.editor.move_stage_up(1)
        self.assertEqual(
            [stage.name for stage in self.editor.draft.stages],
            ["Analyse", standard_chain("da").stages[0].name],
        )
        self.assertFalse(self.path.exists())

    def test_create_copy_rename_delete_and_unique_names(self):
        """Catches destructive or ambiguous chain-list operations."""
        self.assertTrue(self.editor.create_chain("Ny"))
        self.assertTrue(self.editor.save_chain())
        self.assertFalse(self.editor.copy_chain("Ny"))
        self.assertTrue(self.editor.copy_chain("Kopi"))
        self.assertFalse(self.editor.rename_chain("Ny"))
        self.assertTrue(self.editor.rename_chain("Omdøbt"))
        self.assertEqual(self.editor.draft.name, "Omdøbt")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=False):
            self.assertTrue(self.editor.delete_chain())
        self.assertEqual(self.editor.draft.name, "Standard")
        self.assertEqual([chain.name for chain in load_chains(self.path)], ["Ny"])

    def test_builtin_cannot_be_deleted_or_overwritten(self):
        """Catches accidental persistence of the read-only built-in default."""
        self.assertFalse(self.editor.delete_chain())
        self.assertFalse(self.editor.rename_chain("Changed"))
        self.assertFalse(self.editor.save_chain())
        self.assertEqual(self.editor.draft, standard_chain("da"))
        self.assertFalse(self.path.exists())

    def test_help_button_opens_prompt_chain_instructions_without_editing(self):
        """Catches the editor leaving users unable to find how to copy Standard."""
        self.button("Hjælp").invoke()
        windows = [child for child in self.editor.winfo_children() if isinstance(child, tk.Toplevel)]
        self.assertEqual(len(windows), 1)
        pending = [windows[0]]
        visible_text = []
        selected_tabs = []
        while pending:
            widget = pending.pop()
            if isinstance(widget, tk.Text):
                visible_text.append(widget.get("1.0", "end-1c"))
                self.assertEqual(widget.cget("state"), "disabled")
            if isinstance(widget, ttk.Notebook):
                selected_tabs.append(widget.tab(widget.select(), "text"))
            pending.extend(widget.winfo_children())
        guide = "\n".join(visible_text)
        self.assertEqual(selected_tabs, ["Promptkæder"])
        self.assertIn("Standard", guide)
        self.assertIn("Kopiér", guide)
        self.assertIn("{{previous_output}}", guide)
        self.assertEqual(self.editor.draft, standard_chain("da"))
        self.assertFalse(self.path.exists())

    def test_editor_buttons_share_width_and_fit_at_normal_and_minimum_size(self):
        """Catches editor commands becoming uneven or clipped after uniform sizing."""
        try:
            for size in ("1020x760", "750x580"):
                with self.subTest(size=size):
                    self.editor.geometry(size)
                    self.editor.deiconify()
                    self.editor.update()
                    pending = [self.editor]
                    buttons = []
                    while pending:
                        widget = pending.pop()
                        if isinstance(widget, ttk.Button):
                            buttons.append(widget)
                        pending.extend(widget.winfo_children())
                    self.assertEqual(len(buttons), 12)
                    self.assertEqual(len({button.winfo_width() for button in buttons}), 1)
                    for button in buttons:
                        self.assertGreaterEqual(button.winfo_rootx(), self.editor.winfo_rootx())
                        self.assertLessEqual(
                            button.winfo_rootx() + button.winfo_width(),
                            self.editor.winfo_rootx() + self.editor.winfo_width(),
                        )
                        self.assertGreaterEqual(button.winfo_rooty(), self.editor.winfo_rooty())
                        self.assertLessEqual(
                            button.winfo_rooty() + button.winfo_height(),
                            self.editor.winfo_rooty() + self.editor.winfo_height(),
                        )
        finally:
            self.editor.withdraw()
            self.editor.update()

    def test_cannot_delete_final_stage(self):
        """Catches a chain becoming unexecutable after its last stage is removed."""
        self.editor.copy_standard_chain("Min kæde")
        self.assertFalse(self.editor.delete_stage(0))
        self.assertEqual(len(self.editor.draft.stages), 1)

    def test_edit_all_prompt_fields_then_save_and_reopen(self):
        """Catches visible prompt edits not reaching atomic storage or a fresh editor."""
        self.editor.copy_standard_chain("Redigeret")
        self.editor.system_text.delete("1.0", "end")
        self.editor.system_text.insert("1.0", "Systeminstruktion")
        self.editor.user_text.delete("1.0", "end")
        self.editor.user_text.insert("1.0", "Story: {{user_story}}")
        self.editor.repair_text.delete("1.0", "end")
        self.editor.repair_text.insert("1.0", "Reparation: {{validation_error}}")
        self.assertTrue(self.editor.save_chain())
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(load_chains(self.path)[0].stages[0].system_prompt, "Systeminstruktion")
        self.assertEqual(load_chains(self.path)[0].stages[0].user_prompt, "Story: {{user_story}}")
        self.assertEqual(load_chains(self.path)[0].repair_prompt, "Reparation: {{validation_error}}")
        reopened = PromptChainEditor(self.root, self.path, "da", self.saved.append)
        reopened.withdraw()
        self.addCleanup(reopened.destroy)
        self.assertTrue(reopened.switch_chain("Redigeret"))
        self.assertEqual(reopened.system_text.get("1.0", "end-1c"), "Systeminstruktion")

    def test_invalid_prompt_does_not_replace_saved_file(self):
        """Catches invalid placeholders reaching disk before validation."""
        self.editor.copy_standard_chain("Valid")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        self.editor.user_text.delete("1.0", "end")
        self.editor.user_text.insert("1.0", "{{typo}}")
        self.assertFalse(self.editor.save_chain())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.editor.user_text.get("1.0", "end-1c"), "{{typo}}")

    def test_corrupt_file_warns_and_remains_untouched(self):
        """Catches recovery overwriting an unreadable chain file."""
        self.editor.destroy()
        original = b"{ not valid JSON"
        self.path.write_bytes(original)
        with patch("prompt_chain_editor.messagebox.showwarning") as warning:
            recovered = PromptChainEditor(self.root, self.path, "da", self.saved.append)
        recovered.withdraw()
        self.addCleanup(recovered.destroy)
        self.assertTrue(warning.called)
        self.assertEqual(recovered.draft, standard_chain("da"))
        recovered.copy_standard_chain("New")
        self.assertFalse(recovered.save_chain())
        self.assertEqual(self.path.read_bytes(), original)

    def test_switch_respects_save_discard_cancel(self):
        """Catches switching chains after an unsaved edit without honoring the choice."""
        other = PromptChain("Other", "da", (PromptStage("Stage", "Rules", "{{user_story}}"),), "Repair")
        save_chains(self.path, [other])
        self.editor.saved_chains = load_chains(self.path)
        self.editor.copy_standard_chain("Draft")
        self.editor.system_text.delete("1.0", "end")
        self.editor.system_text.insert("1.0", "Unsaved")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.editor.switch_chain("Other"))
        self.assertEqual(self.editor.system_text.get("1.0", "end-1c"), "Unsaved")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=False):
            self.assertTrue(self.editor.switch_chain("Other"))
        self.assertEqual(load_chains(self.path), [other])
        self.editor.copy_chain("Saved draft")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=True):
            self.assertTrue(self.editor.switch_chain("Standard"))
        self.assertEqual([chain.name for chain in load_chains(self.path)], ["Other", "Saved draft"])

    def test_close_respects_cancel_and_discard(self):
        """Catches the window closing or writing on an unwanted choice."""
        self.editor.copy_standard_chain("Unsaved")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.editor.close())
        self.assertTrue(self.editor.winfo_exists())
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=False):
            self.assertTrue(self.editor.close())
        self.assertFalse(self.path.exists())

    def test_create_does_not_discard_edited_chain_when_cancelled(self):
        """Catches the Opret action bypassing the chain-switch confirmation."""
        self.editor.copy_standard_chain("Current")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        self.editor.system_text.delete("1.0", "end")
        self.editor.system_text.insert("1.0", "Still editing")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.editor.create_chain("Next"))
        self.assertEqual(self.editor.draft.name, "Current")
        self.assertEqual(self.editor.system_text.get("1.0", "end-1c"), "Still editing")
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_atomic_save_keeps_disk_and_visible_draft(self):
        """Catches failed storage clearing edits or reporting a save callback."""
        self.editor.copy_standard_chain("Saved")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        self.editor.system_text.delete("1.0", "end")
        self.editor.system_text.insert("1.0", "Edited instructions")
        with patch("prompt_chain_editor.save_chains", side_effect=OSError("locked")):
            self.assertFalse(self.editor.save_chain())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.editor.system_text.get("1.0", "end-1c"), "Edited instructions")
        self.assertEqual(len(self.saved), 1)

    def test_selector_does_not_follow_stale_name_after_rename_save(self):
        """Catches StopIteration when Save removes the selected old name."""
        self.editor.copy_standard_chain("A")
        self.assertTrue(self.editor.save_chain())
        self.assertTrue(self.editor.rename_chain("B"))
        callback_errors = []
        self.root.report_callback_exception = lambda *error: callback_errors.append(error)
        self.editor.chain_box.set("A")
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=True):
            self.editor.chain_box.event_generate("<<ComboboxSelected>>")
        self.assertEqual(callback_errors, [])
        self.assertEqual(self.editor.draft.name, "B")
        self.assertEqual(self.editor.chain_var.get(), "B")
        self.assertNotIn("A", self.editor.chain_box.cget("values"))
        self.assertEqual([chain.name for chain in load_chains(self.path)], ["B"])

    def test_delete_button_waits_for_explicit_save(self):
        """Catches Slet writing to disk before Gem kæde is clicked."""
        self.editor.copy_standard_chain("A")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        callbacks_before = len(self.saved)
        with patch("prompt_chain_editor.messagebox.askyesno", return_value=True):
            self.button("Slet").invoke()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(self.saved), callbacks_before)
        self.assertTrue(self.editor.dirty)
        self.button("Gem kæde").invoke()
        self.assertEqual(load_chains(self.path), [])
        self.assertEqual(len(self.saved), callbacks_before + 1)

    def test_cancel_or_discard_pending_delete_keeps_disk(self):
        """Catches a queued deletion leaking to disk after Cancel or Discard."""
        self.editor.copy_standard_chain("A")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        with patch("prompt_chain_editor.messagebox.askyesno", return_value=True):
            self.button("Slet").invoke()
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.editor.close())
        self.assertTrue(self.editor.winfo_exists())
        self.assertEqual(self.path.read_bytes(), original)
        with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=False):
            self.assertTrue(self.editor.close())
        self.assertEqual(self.path.read_bytes(), original)

    def test_delete_button_cancel_preserves_dirty_text(self):
        """Catches Slet silently discarding an edited stored chain."""
        self.editor.copy_standard_chain("A")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        self.editor.system_text.delete("1.0", "end")
        self.editor.system_text.insert("1.0", "Uncommitted instructions")
        with patch("prompt_chain_editor.messagebox.askyesno", return_value=True):
            with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
                self.button("Slet").invoke()
        self.assertEqual(self.editor.draft.name, "A")
        self.assertEqual(self.editor.system_text.get("1.0", "end-1c"), "Uncommitted instructions")
        self.assertEqual(self.path.read_bytes(), original)

    def test_copy_button_cancel_preserves_dirty_text(self):
        """Catches Kopiér replacing an edited draft despite Cancel."""
        self.editor.copy_standard_chain("A")
        self.assertTrue(self.editor.save_chain())
        original = self.path.read_bytes()
        self.editor.user_text.delete("1.0", "end")
        self.editor.user_text.insert("1.0", "Unsaved {{user_story}}")
        with patch("prompt_chain_editor.simpledialog.askstring", return_value="B"):
            with patch("prompt_chain_editor.messagebox.askyesnocancel", return_value=None):
                self.button("Kopiér").invoke()
        self.assertEqual(self.editor.draft.name, "A")
        self.assertEqual(self.editor.user_text.get("1.0", "end-1c"), "Unsaved {{user_story}}")
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
