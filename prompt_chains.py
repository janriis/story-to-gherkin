"""Validated, local prompt-chain profiles and their JSON storage."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile


class PromptChainError(ValueError):
    """A prompt-chain profile or its on-disk representation is invalid."""


@dataclass(frozen=True)
class PromptStage:
    name: str
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class PromptChain:
    name: str
    language: str
    stages: tuple[PromptStage, ...]
    repair_prompt: str


_VERSION = 1
_PLACEHOLDER = re.compile(r"{{(.*?)}}", re.DOTALL)
_STAGE_VARIABLES = {"user_story", "test_basis", "previous_output", "language"}
_REPAIR_VARIABLES = _STAGE_VARIABLES | {"validation_error", "invalid_output"}
_LANGUAGES = {"da", "en"}


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptChainError(f"{label} must not be empty")
    return value


def _placeholders(template: object, allowed: set[str], label: str) -> set[str]:
    if not isinstance(template, str):
        raise PromptChainError(f"{label} must be text")
    found = set(_PLACEHOLDER.findall(template))
    unknown = found - allowed
    if unknown:
        raise PromptChainError(f"unknown placeholder {sorted(unknown)[0]}")
    return found


def validate_chain(chain: PromptChain) -> None:
    """Validate a chain before it is saved or used for model calls."""
    if not isinstance(chain, PromptChain):
        raise PromptChainError("chain must be a PromptChain")
    _require_text(chain.name, "name")
    if not isinstance(chain.language, str) or chain.language not in _LANGUAGES:
        raise PromptChainError("language must be da or en")
    if not isinstance(chain.stages, tuple) or not chain.stages:
        raise PromptChainError("chain must contain at least one stage")

    for index, stage in enumerate(chain.stages):
        if not isinstance(stage, PromptStage):
            raise PromptChainError("stage must be a PromptStage")
        _require_text(stage.name, "stage name")
        _require_text(stage.system_prompt, "system prompt")
        _require_text(stage.user_prompt, "user prompt")
        variables = (
            _placeholders(stage.system_prompt, _STAGE_VARIABLES, "system prompt")
            | _placeholders(stage.user_prompt, _STAGE_VARIABLES, "user prompt")
        )
        if index == 0 and "previous_output" in variables:
            raise PromptChainError("first stage must not use previous_output")
        if index > 0 and "previous_output" not in _placeholders(
            stage.user_prompt, _STAGE_VARIABLES, "user prompt"
        ):
            raise PromptChainError("later stages require previous_output in user prompt")

    _require_text(chain.repair_prompt, "repair_prompt")
    _placeholders(chain.repair_prompt, _REPAIR_VARIABLES, "repair prompt")


def _validate_chain_list(chains: list[PromptChain]) -> None:
    if not isinstance(chains, list):
        raise PromptChainError("chains must be a list")
    seen: set[tuple[str, str]] = set()
    for chain in chains:
        validate_chain(chain)
        if chain.name.casefold() == "standard":
            raise PromptChainError("Standard is reserved for the built-in chain")
        key = (chain.name, chain.language)
        if key in seen:
            raise PromptChainError(f"duplicate chain name {chain.name} for {chain.language}")
        seen.add(key)


def render_prompt(
    template: str,
    *,
    story: str,
    test_basis: str,
    previous_output: str,
    language: str,
    validation_error: str = "",
    invalid_output: str = "",
) -> str:
    """Render a template once, preserving placeholder-like text in input data."""
    if language not in _LANGUAGES:
        raise PromptChainError("language must be da or en")
    _placeholders(template, _REPAIR_VARIABLES, "template")

    def block(tag: str, value: str) -> str:
        if not isinstance(value, str):
            raise PromptChainError(f"{tag} must be text")
        return f"<{tag}>\n{value}\n</{tag}>"

    values = {
        "user_story": block("user_story", story),
        "test_basis": block("test_basis", test_basis),
        "previous_output": block("previous_output", previous_output),
        "language": language,
        "validation_error": block("validation_error", validation_error),
        "invalid_output": block("invalid_output", invalid_output),
    }
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def _chain_to_json(chain: PromptChain) -> dict[str, object]:
    return {
        "name": chain.name,
        "language": chain.language,
        "stages": [
            {
                "name": stage.name,
                "system_prompt": stage.system_prompt,
                "user_prompt": stage.user_prompt,
            }
            for stage in chain.stages
        ],
        "repair_prompt": chain.repair_prompt,
    }


def _chain_from_json(value: object) -> PromptChain:
    if not isinstance(value, dict):
        raise PromptChainError("chain entry must be an object")
    try:
        raw_stages = value["stages"]
        if not isinstance(raw_stages, list):
            raise PromptChainError("stages must be a list")
        stages = tuple(
            PromptStage(
                stage["name"], stage["system_prompt"], stage["user_prompt"]
            )
            for stage in raw_stages
            if isinstance(stage, dict)
        )
        if len(stages) != len(raw_stages):
            raise PromptChainError("stage entry must be an object")
        chain = PromptChain(value["name"], value["language"], stages, value["repair_prompt"])
    except KeyError as error:
        raise PromptChainError(f"missing chain field {error.args[0]}") from error
    validate_chain(chain)
    return chain


def load_chains(path: Path) -> list[PromptChain]:
    """Load and validate user-defined profiles without changing their source file."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PromptChainError(f"could not read prompt chains: {error}") from error
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload["version"] != _VERSION
    ):
        raise PromptChainError("unknown prompt chain version")
    raw_chains = payload.get("chains")
    if not isinstance(raw_chains, list):
        raise PromptChainError("chains must be a list")
    chains = [_chain_from_json(value) for value in raw_chains]
    _validate_chain_list(chains)
    return chains


def save_chains(path: Path, chains: list[PromptChain]) -> None:
    """Atomically write validated profiles, leaving an old file intact on failure."""
    _validate_chain_list(chains)
    payload = {"version": _VERSION, "chains": [_chain_to_json(chain) for chain in chains]}
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def find_chain(chains: list[PromptChain], name: str, language: str) -> PromptChain:
    """Find one unambiguous chain for the selected language."""
    _validate_chain_list(chains)
    for chain in chains:
        if chain.name == name and chain.language == language:
            return chain
    raise PromptChainError(f"unknown chain {name} for {language}")


def standard_chain(language: str) -> PromptChain:
    """Return a fresh valid built-in profile that callers may copy and edit."""
    if language == "da":
        return PromptChain(
            "Standard", "da",
            (PromptStage(
                "Skriv scenarier",
                "Du er en erfaren testanalytiker. Skriv kun gyldig dansk Gherkin, "
                "med '# language: da' som første linje. User storyen kan være fri "
                "tekst i én eller flere linjer uden fast skabelon. Udled målet, "
                "men opfind ikke detaljer uden belæg i user story eller testbasis.",
                "Skriv Gherkin-scenarier for denne user story:\n{{user_story}}\n"
                "Supplerende testbasis:\n{{test_basis}}",
            ),),
            "Ret Gherkin-svaret efter denne valideringsfejl: {{validation_error}}\n"
            "Ugyldigt svar: {{invalid_output}}",
        )
    if language == "en":
        return PromptChain(
            "Standard", "en",
            (PromptStage(
                "Write scenarios",
                "You are an experienced test analyst. Write only valid English Gherkin, "
                "with '# language: en' as the first line. The user story may be free-form "
                "text on one or more lines without a fixed template. Infer its goal, "
                "but do not invent details unsupported by the story or test basis.",
                "Write Gherkin scenarios for this user story:\n{{user_story}}\n"
                "Additional test basis:\n{{test_basis}}",
            ),),
            "Repair the Gherkin answer using this validation error: {{validation_error}}\n"
            "Invalid answer: {{invalid_output}}",
        )
    raise PromptChainError("language must be da or en")
