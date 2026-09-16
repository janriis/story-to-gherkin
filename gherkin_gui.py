"""Local desktop front end for Danish and English Gherkin generation."""

import json
import inspect
import os
import queue
import tempfile
import threading
import tkinter as tk
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

from error_log import log_error
from gherkin_story import OllamaError, ValidationError, _write_feature, generate_feature, validate_gherkin
from gherkin_help import GherkinHelp
from prompt_chain_editor import PromptChainEditor
from prompt_chains import PromptChain, PromptChainError, find_chain, load_chains
from test_basis import read_test_basis
from ui_layout import ACTION_BUTTON_WIDTH, RIGHT_BUTTON_INSET


DEFAULT_SETTINGS = {"ollama_url": "http://localhost:11434", "model": "llama3.2", "language": "da"}


def normalize_local_model(value: str) -> str:
    """Reject Ollama's explicitly cloud-backed model tags."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Vælg en model før du fortsætter.")
    model = value.strip()
    if model.casefold().endswith(":cloud"):
        raise ValueError("Cloud-modeller må ikke bruges til user stories. Vælg en lokal model.")
    return model


def normalize_local_url(value: str) -> str:
    """Allow only a plain HTTP loopback Ollama base URL."""
    if not isinstance(value, str):
        raise ValueError("Ollama-adressen skal være tekst.")
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError as error:
        raise ValueError("Ollama-adressen er ugyldig.") from error
    if (
        parts.scheme != "http"
        or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
        or port == 0
    ):
        raise ValueError("Kun en lokal Ollama-adresse uden sti er tilladt.")
    return f"http://{parts.netloc}"


def load_settings(path: Path) -> tuple[dict[str, str], str | None]:
    """Read saved model, endpoint and language or use first-run defaults."""
    if not path.exists():
        return DEFAULT_SETTINGS.copy(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Indstillingerne har forkert format.")
        url = normalize_local_url(data.get("ollama_url"))
        model = normalize_local_model(data.get("model"))
        language = data.get("language", "da")
        if language not in {"da", "en"}:
            raise ValueError("Ugyldigt sprog i indstillingerne.")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        log_error("load_settings", error)
        return DEFAULT_SETTINGS.copy(), "Gemte indstillinger kunne ikke læses; standardvalg bruges."
    return {"ollama_url": url, "model": model, "language": language}, None


def save_settings(path: Path, url: str, model: str, language: str = "da") -> None:
    """Atomically persist only the local endpoint, model and language."""
    normalized_url = normalize_local_url(url)
    model = normalize_local_model(model)
    if language not in {"da", "en"}:
        raise ValueError("Vælg dansk eller engelsk som sprog.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".gherkin-gui-",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"ollama_url": normalized_url, "model": model, "language": language}, stream, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fetch_models(url: str, timeout: float = 5.0) -> list[str]:
    """List model names advertised by the selected local Ollama service."""
    endpoint = normalize_local_url(url) + "/api/tags"
    try:
        with urllib.request.urlopen(endpoint, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeError) as error:
        raise OllamaError(f"Kunne ikke hente modeller fra lokal Ollama: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise OllamaError("Ollama returnerede en ugyldig modelliste.")
    return [
        item["name"]
        for item in data["models"]
        if isinstance(item, dict) and isinstance(item.get("name"), str)
        and item["name"].strip() and not item["name"].strip().casefold().endswith(":cloud")
    ]


class GherkinGui(tk.Tk):
    """Desktop front end for entering a story and reading validated Gherkin."""

    def report_callback_exception(self, exc, value, tb) -> None:
        """Capture Tk callback errors, which pythonw would otherwise hide."""
        log_error("gui_callback", value)
        self.status_var.set("Uventet fejl. Se logs/gherkin-errors.log.")

    def __init__(
        self,
        settings_path: Path | None = None,
        generator=generate_feature,
        model_fetcher=fetch_models,
        chain_path: Path | None = None,
    ):
        super().__init__()
        self.settings_path = settings_path or Path(__file__).with_name("gherkin_gui_settings.json")
        self.chain_path = chain_path or Path(__file__).with_name("gherkin_prompt_chains.json")
        self._generator = generator
        self._model_fetcher = model_fetcher
        self._results: queue.Queue[tuple[str, bool, object]] = queue.Queue()
        self._busy = False
        self._closed = False
        self._chains: list[PromptChain] = []
        self._stage_outputs: list[tuple[int, str, str]] = []
        self._last_stage = ""
        self.stage_window: tk.Toplevel | None = None
        self.chain_editor: PromptChainEditor | None = None
        settings, warning = load_settings(self.settings_path)
        self.url_var = tk.StringVar(value=settings["ollama_url"])
        self.model_var = tk.StringVar(value=settings["model"])
        self.language_var = tk.StringVar(value=settings["language"])
        self.chain_var = tk.StringVar(value="Standard")
        self._active_language = settings["language"]
        self._selected_language = settings["language"]
        self._changing_language = False
        self._output_language = settings["language"]
        self.status_var = tk.StringVar(value=warning or "Klar til at generere scenarier.")
        self.title("Gherkin fra user story")
        self.geometry("980x800")
        self.minsize(720, 640)
        self._build_widgets()
        self.language_var.trace_add("write", self._language_changed)
        self.reload_chains()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._poll_id = self.after(100, self._poll_results)

    def _build_widgets(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=2)
        container.rowconfigure(4, weight=1)
        container.rowconfigure(7, weight=2)

        setup = ttk.LabelFrame(container, text="Lokal Ollama", padding=10)
        setup.grid(row=0, column=0, sticky="ew")
        setup.columnconfigure(1, weight=1)
        ttk.Label(setup, text="Serveradresse").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(setup, textvariable=self.url_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(setup, text="Model").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.model_box = ttk.Combobox(setup, textvariable=self.model_var)
        self.model_box.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        self.connection_button = ttk.Button(
            setup, text="Kontrollér forbindelse", command=self.check_connection,
            width=ACTION_BUTTON_WIDTH,
        )
        self.connection_button.grid(row=0, column=2, padx=(10, 0), sticky="ew")
        self.settings_button = ttk.Button(
            setup, text="Gem indstillinger", command=self.save_current_settings,
            width=ACTION_BUTTON_WIDTH,
        )
        self.settings_button.grid(row=1, column=2, padx=(10, 0), pady=(8, 0), sticky="ew")
        ttk.Label(setup, text="Scenariesprog").grid(row=2, column=0, sticky="w", pady=(8, 0))
        language_choices = ttk.Frame(setup)
        language_choices.grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(language_choices, text="Dansk", variable=self.language_var, value="da").pack(side="left")
        ttk.Radiobutton(language_choices, text="English", variable=self.language_var, value="en").pack(side="left", padx=(14, 0))
        self.help_button = ttk.Button(
            setup, text="Hjælp", command=lambda: GherkinHelp(self), width=ACTION_BUTTON_WIDTH,
        )
        self.help_button.grid(row=2, column=2, padx=(10, 0), pady=(8, 0), sticky="ew")
        ttk.Label(setup, text="Promptkæde").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.chain_box = ttk.Combobox(setup, textvariable=self.chain_var, state="readonly")
        self.chain_box.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        self.edit_chains_button = ttk.Button(
            setup, text="Redigér kæder", command=self.edit_chains, width=ACTION_BUTTON_WIDTH,
        )
        self.edit_chains_button.grid(row=3, column=2, padx=(10, 0), pady=(8, 0), sticky="ew")

        story_header = ttk.Frame(container)
        story_header.grid(row=1, column=0, sticky="ew", pady=(12, 4))
        ttk.Label(story_header, text="User story").pack(side="left")
        ttk.Button(
            story_header, text="Indlæs tekstfil", command=self.load_story_file,
            width=ACTION_BUTTON_WIDTH,
        ).pack(side="right", padx=(0, RIGHT_BUTTON_INSET))
        self.story_text = scrolledtext.ScrolledText(container, wrap="word", height=8, undo=True)
        self.story_text.grid(row=2, column=0, sticky="nsew")

        basis_header = ttk.Frame(container)
        basis_header.grid(row=3, column=0, sticky="ew", pady=(12, 4))
        ttk.Label(basis_header, text="Testbasis / acceptkriterier (valgfrit)").pack(side="left")
        self.load_basis_button = ttk.Button(
            basis_header, text="Indlæs testbasis", command=self.load_test_basis_file,
            width=ACTION_BUTTON_WIDTH,
        )
        self.load_basis_button.pack(side="right", padx=(0, RIGHT_BUTTON_INSET))
        self.test_basis_text = scrolledtext.ScrolledText(container, wrap="word", height=5, undo=True)
        self.test_basis_text.grid(row=4, column=0, sticky="nsew")

        actions = ttk.Frame(container)
        actions.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.generate_button = ttk.Button(
            actions, text="Generér scenarier", command=self.generate, width=ACTION_BUTTON_WIDTH,
        )
        self.generate_button.pack(side="left")
        ttk.Button(
            actions, text="Vis mellemresultater", command=self.show_stage_outputs,
            width=ACTION_BUTTON_WIDTH,
        ).pack(side="left", padx=(10, 0))
        self.save_button = ttk.Button(
            actions, text="Gem .feature", command=self.save_feature,
            state="disabled", width=ACTION_BUTTON_WIDTH,
        )
        self.save_button.pack(side="right", padx=(0, RIGHT_BUTTON_INSET))

        ttk.Label(container, text="Valideret Gherkin – gennemgå indholdet fagligt før brug.").grid(
            row=6, column=0, sticky="w", pady=(12, 4)
        )
        self.output_text = scrolledtext.ScrolledText(container, wrap="none", height=10, undo=True)
        self.output_text.grid(row=7, column=0, sticky="nsew")
        ttk.Label(container, textvariable=self.status_var, wraplength=900).grid(
            row=8, column=0, sticky="ew", pady=(10, 0)
        )

    def _language_changed(self, *_args) -> None:
        if self._changing_language:
            return
        language = self.language_var.get()
        if language != self._selected_language:
            editor = self.chain_editor
            if editor is not None and editor.winfo_exists():
                self._changing_language = True
                try:
                    if not editor.switch_language(language):
                        self.language_var.set(self._selected_language)
                        return
                finally:
                    self._changing_language = False
            self._selected_language = language
        choices = ["Standard", *(chain.name for chain in self._chains
                                 if chain.language == language)]
        self.chain_box.configure(values=choices)
        if self.chain_var.get() not in choices:
            self.chain_var.set("Standard")

    def reload_chains(self) -> None:
        """Refresh the picker from the local profile file, keeping corrupt data intact."""
        try:
            self._chains = load_chains(self.chain_path)
        except PromptChainError as error:
            log_error("load_chains", error)
            self._chains = []
            self.status_var.set(f"Promptkædefil kunne ikke læses; kun Standard bruges. Filen er bevaret: {error}")
        self._language_changed()

    def edit_chains(self) -> None:
        """Open the separate chain editor when no model call is active."""
        if self._busy:
            return
        if self.chain_editor is not None and self.chain_editor.winfo_exists():
            self.chain_editor.lift()
            return
        self.chain_editor = PromptChainEditor(
            self, self.chain_path, self.language_var.get(), on_saved=lambda _chains: self._chains_saved()
        )

    def _chains_saved(self) -> None:
        self.reload_chains()
        selected = self.chain_editor.draft.name
        if selected in self.chain_box["values"]:
            self.chain_var.set(selected)

    def show_stage_outputs(self) -> None:
        """Show unvalidated drafts separately from the savable feature output."""
        if self.stage_window is not None and self.stage_window.winfo_exists():
            self.stage_window.lift()
            return
        self.stage_window = tk.Toplevel(self)
        self.stage_window.title("Mellemresultater – ikke valideret")
        self.stage_window.geometry("760x520")
        self.stage_output_text = scrolledtext.ScrolledText(self.stage_window, wrap="word")
        self.stage_output_text.pack(fill="both", expand=True, padx=12, pady=12)
        self._render_stage_outputs()

    def _render_stage_outputs(self) -> None:
        if self.stage_window is None or not self.stage_window.winfo_exists():
            return
        self.stage_output_text.configure(state="normal")
        self.stage_output_text.delete("1.0", "end")
        for index, name, result in self._stage_outputs:
            self.stage_output_text.insert("end", f"Trin {index}: {name}\n{result}\n\n")
        self.stage_output_text.configure(state="disabled")

    def generate(self) -> None:
        """Start a nonblocking generation using only a local Ollama URL."""
        if self._busy:
            return
        story = self.story_text.get("1.0", "end-1c").strip()
        basis = self.test_basis_text.get("1.0", "end-1c").strip()
        if not story:
            self.status_var.set("User story må ikke være tom.")
            return
        self.output_text.delete("1.0", "end")
        self.save_button.configure(state="disabled")
        try:
            url = normalize_local_url(self.url_var.get())
            model = normalize_local_model(self.model_var.get())
            language = self.language_var.get()
            if language not in {"da", "en"}:
                raise ValueError("Vælg dansk eller engelsk som sprog.")
            chain_name = self.chain_var.get()
            chain = None if chain_name == "Standard" else find_chain(self._chains, chain_name, language)
        except ValueError as error:
            log_error("prepare_generate", error)
            self.status_var.set(str(error))
            return
        self._active_language = language
        self._stage_outputs = []
        self._last_stage = ""
        self._render_stage_outputs()
        self.status_var.set("Genererer scenarier ...")
        def stage_event(event: str, index: int, name: str, text: str) -> None:
            self._results.put(("stage", True, (event, index, name, text)))

        kwargs = {"language": language}
        if chain is not None:
            kwargs.update(chain=chain, on_stage=stage_event)
        else:
            try:
                parameters = inspect.signature(self._generator).parameters
                supports_stage_events = "on_stage" in parameters or any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
            except (TypeError, ValueError):
                supports_stage_events = False
            if supports_stage_events:
                kwargs["on_stage"] = stage_event
        if basis:
            kwargs["test_basis"] = basis
        self._start_worker("generate", lambda: self._generator(story, model, url, **kwargs))

    def _start_worker(self, operation: str, work) -> None:
        self._busy = True
        self.generate_button.configure(state="disabled")
        self.connection_button.configure(state="disabled")
        self.load_basis_button.configure(state="disabled")
        self.chain_box.configure(state="disabled")
        self.edit_chains_button.configure(state="disabled")

        def worker() -> None:
            try:
                self._results.put((operation, True, work()))
            except Exception as error:
                log_error(operation, error)
                self._results.put((operation, False, str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self) -> None:
        if self._closed:
            return
        while not self._results.empty():
            operation, success, payload = self._results.get_nowait()
            if operation == "stage":
                event, index, name, result = payload
                self._last_stage = f"trin {index} ({name})"
                if event == "start":
                    self.status_var.set(f"Genererer {self._last_stage} ...")
                elif event == "result":
                    self._stage_outputs.append((index, name, result))
                    self._render_stage_outputs()
                    self.status_var.set(f"{self._last_stage} er færdigt; mellemresultat kan ses separat.")
                continue
            if operation == "generate":
                if success:
                    try:
                        feature = str(payload)
                        validate_gherkin(feature, language=self._active_language)
                    except ValidationError as error:
                        log_error("validate_generated", error)
                        self.status_var.set(f"Ugyldig Gherkin: {error}")
                    else:
                        self.output_text.insert("1.0", feature)
                        self._output_language = self._active_language
                        self.save_button.configure(state="normal")
                        self.status_var.set("Gherkin valideret. Gennemgå scenarierne fagligt.")
                else:
                    detail = f" ved {self._last_stage}" if self._last_stage else ""
                    self.status_var.set(f"Generering mislykkedes{detail}: {payload}")
            elif operation == "connection":
                if success:
                    names = list(payload)
                    self.model_box.configure(values=names)
                    self.status_var.set(f"Forbindelsen virker. {len(names)} lokale modeller fundet.")
                else:
                    self.status_var.set(f"Forbindelsen mislykkedes: {payload}")
            elif operation == "load_basis":
                if success:
                    self.test_basis_text.delete("1.0", "end")
                    self.test_basis_text.insert("1.0", str(payload))
                    self.status_var.set("Testbasis indlæst. Teksten kan redigeres før generering.")
                else:
                    self.status_var.set(f"Indlæsning af testbasis mislykkedes: {payload}")
            self._busy = False
            self.generate_button.configure(state="normal")
            self.connection_button.configure(state="normal")
            self.load_basis_button.configure(state="normal")
            self.chain_box.configure(state="readonly")
            self.edit_chains_button.configure(state="normal")
        self._poll_id = self.after(100, self._poll_results)

    def check_connection(self) -> None:
        """Refresh the local model list."""
        if self._busy:
            return
        try:
            url = normalize_local_url(self.url_var.get())
        except ValueError as error:
            log_error("check_connection", error)
            self.status_var.set(str(error))
            return
        self.status_var.set("Kontrollerer lokal Ollama-forbindelse ...")
        self._start_worker("connection", lambda: self._model_fetcher(url))

    def save_current_settings(self) -> None:
        """Persist the current local model configuration."""
        try:
            save_settings(self.settings_path, self.url_var.get(), self.model_var.get(), self.language_var.get())
        except (ValueError, OSError) as error:
            log_error("save_settings", error)
            self.status_var.set(f"Indstillinger kunne ikke gemmes: {error}")
        else:
            self.status_var.set("Indstillinger gemt.")

    def load_story_file(self) -> None:
        """Load a UTF-8 story into the editor."""
        chosen = filedialog.askopenfilename(
            parent=self, title="Vælg user story", filetypes=[("Tekstfiler", "*.txt"), ("Alle filer", "*.*")]
        )
        if not chosen:
            return
        try:
            story = Path(chosen).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            log_error("load_story", error)
            self.status_var.set(f"User story kunne ikke indlæses: {error}")
            return
        self.story_text.delete("1.0", "end")
        self.story_text.insert("1.0", story)
        self.status_var.set("User story indlæst.")

    def load_test_basis_file(self) -> None:
        """Extract a local document in the worker without replacing text on error."""
        if self._busy:
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Vælg testbasis",
            filetypes=[("Testbasis", "*.txt *.md *.pdf *.docx")],
        )
        if chosen:
            self.status_var.set("Indlæser testbasis ...")
            self._start_worker("load_basis", lambda: read_test_basis(Path(chosen)))

    def save_feature(self) -> None:
        """Save validated Gherkin to a selected feature file."""
        feature = self.output_text.get("1.0", "end-1c")
        try:
            validate_gherkin(feature, language=self._output_language)
        except ValidationError as error:
            log_error("save_feature", error)
            self.status_var.set(f"Gherkin kan ikke gemmes: {error}")
            return
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Gem Gherkin-feature", defaultextension=".feature",
            filetypes=[("Gherkin-feature", "*.feature")],
        )
        if not chosen:
            return
        try:
            _write_feature(Path(chosen), feature)
        except OSError as error:
            log_error("save_feature", error)
            self.status_var.set(f"Feature kunne ikke gemmes: {error}")
        else:
            self.status_var.set(f"Feature gemt: {chosen}")

    def close(self) -> None:
        if not self._closed:
            if self.chain_editor is not None and self.chain_editor.winfo_exists():
                if not self.chain_editor.close():
                    return
            self._closed = True
            self.after_cancel(self._poll_id)
            self.destroy()


def main() -> None:
    try:
        GherkinGui().mainloop()
    except Exception as error:
        log_error("gui_startup", error)
        raise


if __name__ == "__main__":
    main()
