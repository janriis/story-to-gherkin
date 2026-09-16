import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from prompt_chains import (
    PromptChain,
    PromptChainError,
    PromptStage,
    find_chain,
    load_chains,
    render_prompt,
    save_chains,
    standard_chain,
    validate_chain,
)


class PromptChainValidationTests(unittest.TestCase):
    def setUp(self):
        self.valid_chain = PromptChain(
            "Tjek",
            "da",
            (PromptStage("Analyse", "Følg reglerne", "{{user_story}}"),),
            "Ret svaret med {{validation_error}} og {{invalid_output}}",
        )

    def test_second_stage_requires_previous_output(self):
        """Catches a later stage silently ignoring the prior stage result."""
        chain = PromptChain("Tjek", "da", (
            PromptStage("Analyse", "Regler", "{{user_story}}"),
            PromptStage("Scenarier", "Regler", "Skriv Gherkin"),
        ), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "previous_output"):
            validate_chain(chain)

    def test_first_stage_rejects_previous_output(self):
        """Catches a first stage referring to output that does not exist."""
        chain = PromptChain("Tjek", "da", (
            PromptStage("Analyse", "Regler", "{{previous_output}}"),
        ), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "previous_output"):
            validate_chain(chain)

    def test_empty_chain_name_is_rejected(self):
        """Catches profiles that cannot be selected by a meaningful name."""
        chain = PromptChain("  ", "da", self.valid_chain.stages, "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "name"):
            validate_chain(chain)

    def test_invalid_language_is_rejected(self):
        """Catches a profile being saved outside the supported language choices."""
        chain = PromptChain("Tjek", "sv", self.valid_chain.stages, "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "language"):
            validate_chain(chain)

    def test_empty_stage_list_is_rejected(self):
        """Catches a chain that would make no model calls."""
        chain = PromptChain("Tjek", "da", (), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "stage"):
            validate_chain(chain)

    def test_empty_stage_name_is_rejected(self):
        """Catches stage results that could not identify their source stage."""
        chain = PromptChain("Tjek", "da", (PromptStage("", "Regler", "{{user_story}}"),), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "stage.*name"):
            validate_chain(chain)

    def test_empty_stage_prompt_is_rejected(self):
        """Catches a stage with no instruction content for the model."""
        chain = PromptChain("Tjek", "da", (PromptStage("Analyse", "", "{{user_story}}"),), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "prompt"):
            validate_chain(chain)

    def test_empty_repair_prompt_is_rejected(self):
        """Catches a repair attempt with no repair instruction."""
        chain = PromptChain("Tjek", "da", self.valid_chain.stages, " ")
        with self.assertRaisesRegex(PromptChainError, "repair_prompt"):
            validate_chain(chain)

    def test_unknown_placeholder_is_rejected_even_when_malformed(self):
        """Catches typo placeholders before they reach a model call."""
        chain = PromptChain("Tjek", "da", (
            PromptStage("Analyse", "Regler", "{{user-story}}"),
        ), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "unknown.*user-story"):
            validate_chain(chain)

    def test_placeholder_with_spaces_is_rejected(self):
        """Catches a spaced typo placeholder being silently left in a prompt."""
        chain = PromptChain("Tjek", "da", (
            PromptStage("Analyse", "Regler", "{{ user story }}"),
        ), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "unknown.*user story"):
            validate_chain(chain)

    def test_placeholder_with_line_break_is_rejected(self):
        """Catches a malformed multi-line marker bypassing placeholder validation."""
        chain = PromptChain("Tjek", "da", (
            PromptStage("Analyse", "Regler", "{{user\nstory}}"),
        ), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "unknown.*user"):
            validate_chain(chain)

    def test_repair_variables_are_rejected_from_ordinary_stages(self):
        """Catches repair-only input leaking into ordinary stage templates."""
        chain = PromptChain("Tjek", "da", (
            PromptStage("Analyse", "{{invalid_output}}", "{{user_story}}"),
        ), "Ret svaret")
        with self.assertRaisesRegex(PromptChainError, "invalid_output"):
            validate_chain(chain)

    def test_repair_prompt_accepts_repair_variables(self):
        """Catches rejecting the validation data needed by the repair prompt."""
        self.assertIsNone(validate_chain(self.valid_chain))

    def test_duplicate_name_in_same_language_is_rejected(self):
        """Catches ambiguous selection within one language."""
        duplicate = PromptChain("Tjek", "da", self.valid_chain.stages, "Ret igen")
        with self.assertRaisesRegex(PromptChainError, "duplicate.*Tjek"):
            find_chain([self.valid_chain, duplicate], "Tjek", "da")

    def test_same_name_in_different_languages_is_allowed(self):
        """Catches a global uniqueness rule that blocks translations."""
        english = PromptChain("Tjek", "en", self.valid_chain.stages, "Repair it")
        self.assertEqual(find_chain([self.valid_chain, english], "Tjek", "en"), english)


class PromptRenderingTests(unittest.TestCase):
    def test_input_containing_placeholder_is_not_expanded_again(self):
        """Catches a second substitution pass through user-provided story text."""
        rendered = render_prompt("Story: {{user_story}}", story="tekst {{language}}",
                                 test_basis="", previous_output="", language="da")
        self.assertIn("tekst {{language}}", rendered)
        self.assertIn("<user_story>", rendered)

    def test_text_inputs_are_wrapped_as_data_blocks(self):
        """Catches raw story, basis, and stage output being merged into instructions."""
        rendered = render_prompt(
            "{{user_story}} {{test_basis}} {{previous_output}} {{language}}",
            story="Story", test_basis="Basis", previous_output="Earlier", language="en",
        )
        self.assertEqual(
            rendered,
            "<user_story>\nStory\n</user_story> <test_basis>\nBasis\n</test_basis> "
            "<previous_output>\nEarlier\n</previous_output> en",
        )

    def test_rendering_rejects_unknown_placeholder(self):
        """Catches direct rendering of an unvalidated template with a typo."""
        with self.assertRaisesRegex(PromptChainError, "unknown.*language-code"):
            render_prompt("{{language-code}}", story="", test_basis="", previous_output="", language="da")

    def test_rendering_rejects_wrong_language(self):
        """Catches a renderer producing prompts for unsupported languages."""
        with self.assertRaisesRegex(PromptChainError, "language"):
            render_prompt("{{language}}", story="", test_basis="", previous_output="", language="de")

    def test_standard_chain_is_a_valid_single_stage_copy(self):
        """Catches built-in profiles becoming invalid or sharing mutable stage state."""
        danish = standard_chain("da")
        english = standard_chain("en")
        self.assertEqual(len(danish.stages), 1)
        self.assertNotEqual(danish.stages[0].user_prompt, english.stages[0].user_prompt)
        self.assertIsNone(validate_chain(danish))
        self.assertIsNone(validate_chain(english))


class PromptChainStorageTests(unittest.TestCase):
    def setUp(self):
        self.valid_chain = PromptChain(
            "Local profile", "en",
            (PromptStage("Draft", "Use the rules", "{{user_story}}"),),
            "Repair {{invalid_output}} using {{validation_error}}",
        )

    def test_roundtrip_stores_only_prompts(self):
        """Catches persistence losing a profile or adding non-profile top-level data."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gherkin_prompt_chains.json"
            save_chains(path, [self.valid_chain])
            self.assertEqual(load_chains(path), [self.valid_chain])
            self.assertEqual(set(json.loads(path.read_text(encoding="utf-8"))), {"version", "chains"})

    def test_missing_file_loads_as_no_profiles(self):
        """Catches first launch failing before a user has saved any profile."""
        with TemporaryDirectory() as directory:
            self.assertEqual(load_chains(Path(directory) / "missing.json"), [])

    def test_corrupt_json_raises_without_changing_file(self):
        """Catches a recovery path overwriting a user's damaged profile file."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            original = b"{ definitely not json"
            path.write_bytes(original)
            with self.assertRaisesRegex(PromptChainError, "could not read"):
                load_chains(path)
            self.assertEqual(path.read_bytes(), original)

    def test_unknown_version_raises_without_changing_file(self):
        """Catches silently treating a future profile format as version one."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            original = b'{"version": 2, "chains": []}'
            path.write_bytes(original)
            with self.assertRaisesRegex(PromptChainError, "version"):
                load_chains(path)
            self.assertEqual(path.read_bytes(), original)

    def test_non_integer_version_one_values_are_rejected(self):
        """Catches bool and float JSON versions being mistaken for integer version one."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            for version in (True, 1.0):
                with self.subTest(version=version):
                    original = json.dumps({"version": version, "chains": []}).encode("utf-8")
                    path.write_bytes(original)
                    with self.assertRaisesRegex(PromptChainError, "version"):
                        load_chains(path)
                    self.assertEqual(path.read_bytes(), original)

    def test_array_or_object_language_raises_prompt_chain_error(self):
        """Catches malformed JSON language values escaping as Python TypeError."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            for language in (["da"], {"code": "da"}):
                with self.subTest(language=language):
                    path.write_text(json.dumps({
                        "version": 1,
                        "chains": [{
                            "name": "Malformed",
                            "language": language,
                            "stages": [{
                                "name": "Draft",
                                "system_prompt": "Rules",
                                "user_prompt": "{{user_story}}",
                            }],
                            "repair_prompt": "Repair it",
                        }],
                    }), encoding="utf-8")
                    with self.assertRaisesRegex(PromptChainError, "language"):
                        load_chains(path)

    def test_save_rejects_duplicate_names_before_writing(self):
        """Catches a save replacing an existing file with ambiguous profile names."""
        duplicate = PromptChain("Local profile", "en", self.valid_chain.stages, "Repair it")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            original = b"old profile file"
            path.write_bytes(original)
            with self.assertRaisesRegex(PromptChainError, "duplicate.*Local profile"):
                save_chains(path, [self.valid_chain, duplicate])
            self.assertEqual(path.read_bytes(), original)

    def test_saved_custom_standard_name_is_rejected_without_changing_file(self):
        """Catches a custom profile shadowing the built-in Standard picker entry."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            original = b"existing data"
            path.write_bytes(original)
            custom = PromptChain("Standard", "en", self.valid_chain.stages, self.valid_chain.repair_prompt)
            with self.assertRaisesRegex(PromptChainError, "Standard"):
                save_chains(path, [custom])
            self.assertEqual(path.read_bytes(), original)
            self.assertIsNone(validate_chain(standard_chain("en")))

    def test_read_rejects_custom_standard_name_without_changing_file(self):
        """Catches old JSON with a shadow profile producing an ambiguous GUI choice."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            payload = {"version": 1, "chains": [{
                "name": "Standard", "language": "en",
                "stages": [{"name": "Draft", "system_prompt": "Rules", "user_prompt": "{{user_story}}"}],
                "repair_prompt": "Repair",
            }]}
            original = json.dumps(payload).encode("utf-8")
            path.write_bytes(original)
            with self.assertRaisesRegex(PromptChainError, "Standard"):
                load_chains(path)
            self.assertEqual(path.read_bytes(), original)

    def test_replace_failure_preserves_original_file_and_removes_own_temp_file(self):
        """Catches failed atomic replacement corrupting the prior saved profiles."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            original = b"old profile file"
            path.write_bytes(original)
            with patch("prompt_chains.os.replace", side_effect=OSError("file is locked")):
                with self.assertRaisesRegex(OSError, "locked"):
                    save_chains(path, [self.valid_chain])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob(".chains.json.*.tmp")), [])
