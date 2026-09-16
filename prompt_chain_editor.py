"""Separate Tkinter editor for local prompt-chain profiles."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk
from typing import Callable

from error_log import log_error
from gherkin_help import GherkinHelp
from prompt_chains import (
    PromptChain, PromptChainError, PromptStage, load_chains, save_chains,
    standard_chain, validate_chain,
)
from ui_layout import ACTION_BUTTON_WIDTH


class PromptChainEditor(tk.Toplevel):
    """Keep a draft distinct from stored profiles until an explicit save."""

    def __init__(
        self,
        parent: tk.Misc,
        path: Path,
        language: str,
        on_saved: Callable[[list[PromptChain]], None],
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.language = language
        self.on_saved = on_saved
        self._load_error: PromptChainError | None = None
        try:
            self.saved_chains = load_chains(path)
        except PromptChainError as error:
            log_error("editor_load_chains", error)
            self.saved_chains = []
            self._load_error = error
            messagebox.showwarning(
                "Promptkæder kunne ikke indlæses",
                "Den lokale kædefil er beskadiget eller ukendt. Filen ændres ikke. "
                f"Ret eller flyt den før du gemmer kæder.\n\n{error}", parent=self,
            )
        self.draft = standard_chain(language)
        self._origin_name: str | None = "Standard"
        self._pending_delete_name: str | None = None
        self._selected_stage = 0
        self.dirty = False
        self.status_var = tk.StringVar(value="Standardkæden er skrivebeskyttet; lav en kopi for at redigere.")
        self.chain_var = tk.StringVar(value="Standard")
        self.title("Redigér promptkæder")
        self.geometry("1020x760")
        self.minsize(750, 580)
        self._build_widgets()
        self._show_draft()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_widgets(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=2)
        frame.rowconfigure(4, weight=2)
        frame.rowconfigure(6, weight=1)
        choices = ttk.Frame(frame)
        choices.grid(row=0, column=0, columnspan=2, sticky="ew")
        selector = ttk.Frame(choices)
        selector.pack(fill="x")
        ttk.Label(selector, text="Kæde").pack(side="left")
        self.chain_box = ttk.Combobox(selector, textvariable=self.chain_var, state="readonly", width=28)
        self.chain_box.pack(side="left", padx=(8, 10))
        self.chain_box.bind("<<ComboboxSelected>>", self._chain_chosen)
        chain_actions = ttk.Frame(choices)
        chain_actions.pack(fill="x", pady=(8, 0))
        for label, action in (
            ("Opret", self._create_clicked), ("Kopiér", self._copy_clicked),
            ("Omdøb", self._rename_clicked), ("Slet", self._delete_clicked),
        ):
            ttk.Button(
                chain_actions, text=label, command=action, width=ACTION_BUTTON_WIDTH,
            ).pack(side="left", padx=(0, 6))

        stage_panel = ttk.LabelFrame(frame, text="Trin", padding=8)
        stage_panel.grid(row=1, column=0, rowspan=6, sticky="nsw", pady=(12, 0), padx=(0, 12))
        self.stage_list = tk.Listbox(stage_panel, width=24, height=12, exportselection=False)
        self.stage_list.pack(fill="both", expand=True)
        self.stage_list.bind("<<ListboxSelect>>", self._stage_chosen)
        for label, action in (
            ("Tilføj trin", self._add_stage_clicked),
            ("Omdøb trin", self._rename_stage_clicked),
            ("Slet trin", self._delete_stage_clicked),
            ("Flyt op", lambda: self.move_stage_up(self._selected_stage)),
            ("Flyt ned", lambda: self.move_stage_down(self._selected_stage)),
        ):
            ttk.Button(
                stage_panel, text=label, command=action, width=ACTION_BUTTON_WIDTH,
            ).pack(fill="x", pady=(5, 0))

        ttk.Label(frame, text="Systemprompt").grid(row=1, column=1, sticky="sw", pady=(12, 4))
        self.system_text = scrolledtext.ScrolledText(frame, wrap="word", height=8, undo=True)
        self.system_text.grid(row=2, column=1, sticky="nsew")
        ttk.Label(frame, text="Brugerprompt").grid(row=3, column=1, sticky="sw", pady=(10, 4))
        self.user_text = scrolledtext.ScrolledText(frame, wrap="word", height=8, undo=True)
        self.user_text.grid(row=4, column=1, sticky="nsew")
        ttk.Label(frame, text="Reparationsinstruktion").grid(row=5, column=1, sticky="sw", pady=(10, 4))
        self.repair_text = scrolledtext.ScrolledText(frame, wrap="word", height=5, undo=True)
        self.repair_text.grid(row=6, column=1, sticky="nsew")
        for widget in (self.system_text, self.user_text, self.repair_text):
            widget.bind("<KeyRelease>", self._text_changed)
            widget.bind("<<Paste>>", self._text_changed)
            widget.bind("<<Cut>>", self._text_changed)
        ttk.Label(
            frame,
            text="Pladsholdere: {{user_story}}, {{test_basis}}, {{language}} og fra trin 2 "
                 "{{previous_output}}. Reparationsinstruktion kan også bruge "
                 "{{validation_error}} og {{invalid_output}}. Flere trin kræver ekstra modeltid.",
            wraplength=740, justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 6))
        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, columnspan=2, sticky="ew")
        ttk.Button(
            actions, text="Gem kæde", command=self.save_chain, width=ACTION_BUTTON_WIDTH,
        ).pack(side="left")
        self.help_button = ttk.Button(
            actions, text="Hjælp", command=lambda: GherkinHelp(self, "chains"),
            width=ACTION_BUTTON_WIDTH,
        )
        self.help_button.pack(side="left", padx=(10, 0))
        ttk.Button(
            actions, text="Luk", command=self.close, width=ACTION_BUTTON_WIDTH,
        ).pack(side="right")
        ttk.Label(frame, textvariable=self.status_var, wraplength=900).grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

    def _names(self) -> list[str]:
        return [
            "Standard",
            *(chain.name for chain in self.saved_chains
              if chain.language == self.language and chain.name != self._pending_delete_name),
        ]

    def _available_name(self, name: str, *, current: str | None = None) -> bool:
        name = name.strip()
        if not name:
            self.status_var.set("Giv kæden et navn.")
            return False
        if any(existing.casefold() == name.casefold() and existing != current for existing in self._names()):
            self.status_var.set("Der findes allerede en kæde med det navn.")
            return False
        if self._origin_name is None and self.draft.name.casefold() == name.casefold() and name != current:
            self.status_var.set("Der findes allerede en kæde med det navn.")
            return False
        return True

    def _show_draft(self) -> None:
        names = self._names()
        if self._origin_name is None and self.draft.name not in names:
            names.append(self.draft.name)
        self.chain_box.configure(values=names)
        self.chain_var.set(self.draft.name)
        self.stage_list.delete(0, "end")
        for stage in self.draft.stages:
            self.stage_list.insert("end", stage.name)
        self._selected_stage = min(self._selected_stage, len(self.draft.stages) - 1)
        self.stage_list.selection_set(self._selected_stage)
        self._show_stage()

    def _show_stage(self) -> None:
        stage = self.draft.stages[self._selected_stage]
        for widget, value in (
            (self.system_text, stage.system_prompt),
            (self.user_text, stage.user_prompt),
            (self.repair_text, self.draft.repair_prompt),
        ):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
            if self._origin_name == "Standard":
                widget.configure(state="disabled")

    def _text_changed(self, _event: tk.Event) -> None:
        if self._origin_name != "Standard":
            self.dirty = True

    def _sync_texts(self) -> None:
        if self._origin_name == "Standard":
            return
        stage = self.draft.stages[self._selected_stage]
        changed = replace(
            stage,
            system_prompt=self.system_text.get("1.0", "end-1c"),
            user_prompt=self.user_text.get("1.0", "end-1c"),
        )
        stages = list(self.draft.stages)
        stages[self._selected_stage] = changed
        repair = self.repair_text.get("1.0", "end-1c")
        if changed != stage or repair != self.draft.repair_prompt:
            self.draft = replace(self.draft, stages=tuple(stages), repair_prompt=repair)
            self.dirty = True

    def _stage_chosen(self, _event: tk.Event) -> None:
        selection = self.stage_list.curselection()
        if selection and selection[0] != self._selected_stage:
            self._sync_texts()
            self._selected_stage = selection[0]
            self._show_stage()

    def _chain_chosen(self, _event: tk.Event) -> None:
        self.switch_chain(self.chain_var.get())

    def _confirm_unsaved(self) -> bool:
        self._sync_texts()
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Ugemte ændringer", "Vil du gemme ændringerne i kæden før du fortsætter?", parent=self
        )
        if answer is None:
            return False
        if answer:
            return self.save_chain()
        self._discard_changes()
        return True

    def _discard_changes(self) -> None:
        self._pending_delete_name = None
        if self._origin_name in (None, "Standard"):
            self.draft = standard_chain(self.language)
            self._origin_name = "Standard"
        else:
            self.draft = next(
                chain for chain in self.saved_chains
                if chain.name == self._origin_name and chain.language == self.language
            )
        self._selected_stage = 0
        self.dirty = False
        self._show_draft()

    def switch_chain(self, name: str) -> bool:
        """Navigate to a saved profile after resolving unsaved changes."""
        if name == self.draft.name:
            return True
        if name not in self._names() or not self._confirm_unsaved():
            self.chain_var.set(self.draft.name)
            return False
        # Saving a rename can remove the name chosen before the dialog opened.
        if name not in self._names():
            self.chain_var.set(self.draft.name)
            return False
        if name == "Standard":
            self.draft = standard_chain(self.language)
        else:
            self.draft = next(
                chain for chain in self.saved_chains
                if chain.name == name and chain.language == self.language
            )
        self._origin_name = name
        self._selected_stage = 0
        self.dirty = False
        self._show_draft()
        return True

    def switch_language(self, language: str) -> bool:
        """Change the editor language only after resolving its current draft."""
        if language == self.language:
            return True
        if not self._confirm_unsaved():
            return False
        self.language = language
        self.draft = standard_chain(language)
        self._origin_name = "Standard"
        self._pending_delete_name = None
        self._selected_stage = 0
        self.dirty = False
        self._show_draft()
        return True

    def _start_copy(self, source: PromptChain, name: str) -> bool:
        if not self._available_name(name):
            return False
        self.draft = replace(source, name=name.strip())
        self._origin_name = None
        self._selected_stage = 0
        self.dirty = True
        self._show_draft()
        self.status_var.set("Kladde oprettet. Brug Gem kæde for at gemme den.")
        return True

    def create_chain(self, name: str) -> bool:
        """Create a new editable one-stage draft."""
        if not self._available_name(name) or not self._confirm_unsaved():
            return False
        return self._start_copy(standard_chain(self.language), name)

    def copy_standard_chain(self, name: str) -> bool:
        if not self._available_name(name) or not self._confirm_unsaved():
            return False
        return self._start_copy(standard_chain(self.language), name)

    def copy_chain(self, name: str) -> bool:
        if not self._available_name(name) or not self._confirm_unsaved():
            return False
        return self._start_copy(self.draft, name)

    def rename_chain(self, name: str) -> bool:
        if self._origin_name == "Standard":
            self.status_var.set("Standardkæden kan ikke omdøbes.")
            return False
        if not self._available_name(name, current=self._origin_name or self.draft.name):
            return False
        self._sync_texts()
        self.draft = replace(self.draft, name=name.strip())
        self.dirty = True
        self._show_draft()
        return True

    def delete_chain(self) -> bool:
        """Queue deletion of a saved chain until Gem kæde is pressed."""
        if self._origin_name == "Standard":
            self.status_var.set("Standardkæden kan ikke slettes.")
            return False
        if not self._confirm_unsaved():
            return False
        self._pending_delete_name = self._origin_name if self._origin_name != "Standard" else None
        self.draft = standard_chain(self.language)
        self._origin_name = "Standard"
        self._selected_stage = 0
        self.dirty = self._pending_delete_name is not None
        self._show_draft()
        self.status_var.set(
            "Sletning af kæden afventer Gem kæde." if self.dirty else "Kladden er kasseret."
        )
        return True

    def add_stage(self, name: str) -> bool:
        if self._origin_name == "Standard":
            self.status_var.set("Kopiér standardkæden før du redigerer trin.")
            return False
        if not name.strip():
            self.status_var.set("Giv trinnet et navn.")
            return False
        self._sync_texts()
        stage = PromptStage(name.strip(), "Beskriv opgaven for dette trin.", "{{previous_output}}")
        self.draft = replace(self.draft, stages=(*self.draft.stages, stage))
        self._selected_stage = len(self.draft.stages) - 1
        self.dirty = True
        self._show_draft()
        return True

    def rename_stage(self, name: str, index: int | None = None) -> bool:
        if self._origin_name == "Standard" or not name.strip():
            return False
        self._sync_texts()
        index = self._selected_stage if index is None else index
        if not 0 <= index < len(self.draft.stages):
            return False
        stages = list(self.draft.stages)
        stages[index] = replace(stages[index], name=name.strip())
        self.draft = replace(self.draft, stages=tuple(stages))
        self.dirty = True
        self._show_draft()
        return True

    def delete_stage(self, index: int) -> bool:
        if self._origin_name == "Standard" or len(self.draft.stages) <= 1:
            self.status_var.set("Kæden skal have mindst ét trin.")
            return False
        if not 0 <= index < len(self.draft.stages):
            return False
        self._sync_texts()
        stages = list(self.draft.stages)
        del stages[index]
        self.draft = replace(self.draft, stages=tuple(stages))
        self._selected_stage = min(index, len(stages) - 1)
        self.dirty = True
        self._show_draft()
        return True

    def _move_stage(self, index: int, destination: int) -> bool:
        if self._origin_name == "Standard" or not (0 <= index < len(self.draft.stages)):
            return False
        if not 0 <= destination < len(self.draft.stages):
            return False
        self._sync_texts()
        stages = list(self.draft.stages)
        stages[index], stages[destination] = stages[destination], stages[index]
        self.draft = replace(self.draft, stages=tuple(stages))
        self._selected_stage = destination
        self.dirty = True
        self._show_draft()
        return True

    def move_stage_up(self, index: int) -> bool:
        return self._move_stage(index, index - 1)

    def move_stage_down(self, index: int) -> bool:
        return self._move_stage(index, index + 1)

    def save_chain(self) -> bool:
        """Validate and persist the draft atomically, without losing it on failure."""
        if self._pending_delete_name is not None:
            if self._load_error is not None:
                self.status_var.set("Den beskadigede kædefil bevares; ret den før du gemmer.")
                return False
            remaining = [
                chain for chain in self.saved_chains
                if not (chain.name == self._pending_delete_name and chain.language == self.language)
            ]
            try:
                save_chains(self.path, remaining)
            except (PromptChainError, OSError) as error:
                log_error("delete_chain", error)
                self.status_var.set(f"Kæden kunne ikke slettes: {error}")
                return False
            self.saved_chains = remaining
            self._pending_delete_name = None
            self.dirty = False
            self._show_draft()
            self.status_var.set("Kæden er slettet.")
            self.on_saved(list(remaining))
            return True
        if self._origin_name == "Standard":
            self.status_var.set("Standardkæden kan ikke overskrives.")
            return False
        if self._load_error is not None:
            self.status_var.set("Den beskadigede kædefil bevares; ret den før du gemmer.")
            return False
        self._sync_texts()
        remaining = [
            chain for chain in self.saved_chains
            if not (chain.name == self._origin_name and chain.language == self.language)
        ]
        try:
            validate_chain(self.draft)
            save_chains(self.path, [*remaining, self.draft])
        except (PromptChainError, OSError) as error:
            log_error("save_chain", error)
            self.status_var.set(f"Kæden kunne ikke gemmes: {error}")
            return False
        self.saved_chains = [*remaining, self.draft]
        self._origin_name = self.draft.name
        self.dirty = False
        self._show_draft()
        self.status_var.set("Kæden er gemt.")
        self.on_saved(list(self.saved_chains))
        return True

    def close(self) -> bool:
        if not self._confirm_unsaved():
            return False
        self.destroy()
        return True

    def _ask_name(self, title: str, initial: str = "") -> str | None:
        return simpledialog.askstring(title, "Navn", parent=self, initialvalue=initial)

    def _create_clicked(self) -> None:
        if (name := self._ask_name("Opret kæde")) is not None:
            self.create_chain(name)

    def _copy_clicked(self) -> None:
        if (name := self._ask_name("Kopiér kæde", f"{self.draft.name} kopi")) is not None:
            self.copy_chain(name)

    def _rename_clicked(self) -> None:
        if (name := self._ask_name("Omdøb kæde", self.draft.name)) is not None:
            self.rename_chain(name)

    def _delete_clicked(self) -> None:
        if self._origin_name != "Standard" and messagebox.askyesno(
            "Slet kæde", f"Slet {self.draft.name}?", parent=self
        ):
            self.delete_chain()

    def _add_stage_clicked(self) -> None:
        if (name := self._ask_name("Tilføj trin")) is not None:
            self.add_stage(name)

    def _rename_stage_clicked(self) -> None:
        name = self._ask_name("Omdøb trin", self.draft.stages[self._selected_stage].name)
        if name is not None:
            self.rename_stage(name)

    def _delete_stage_clicked(self) -> None:
        self.delete_stage(self._selected_stage)
