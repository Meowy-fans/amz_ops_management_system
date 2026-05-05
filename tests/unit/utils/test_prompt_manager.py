from pathlib import Path

from src.utils.prompt_manager import PromptManager


def _write_prompt_config(config_dir: Path, content: str):
    prompt_dir = config_dir / "api_clients"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "deepseek.yaml").write_text(content, encoding="utf-8")


def test_prompt_manager_loads_prompts_from_config_dir(tmp_path):
    _write_prompt_config(
        tmp_path,
        """
prompts:
  prod_detail_gen_amz: "Generate detail"
  prod_attribute_enrichment: "Enrich attributes"
""",
    )

    manager = PromptManager(config_dir=tmp_path)

    assert manager.prompts_cache == {
        "prod_detail_gen_amz": "Generate detail",
        "prod_attribute_enrichment": "Enrich attributes",
    }
    assert manager.get_prompt("prod_detail_gen_amz") == "Generate detail"


def test_prompt_manager_defaults_missing_prompts_section_to_empty_cache(tmp_path):
    _write_prompt_config(tmp_path, "other: value")

    manager = PromptManager(config_dir=tmp_path)

    assert manager.prompts_cache == {}


def test_prompt_manager_keeps_empty_cache_when_file_missing(tmp_path):
    manager = PromptManager(config_dir=tmp_path)

    assert manager.prompts_cache == {}
    assert manager.get_prompt("missing") is None


def test_prompt_manager_keeps_empty_cache_when_yaml_is_invalid(tmp_path):
    _write_prompt_config(tmp_path, "prompts: [unterminated")

    manager = PromptManager(config_dir=tmp_path)

    assert manager.prompts_cache == {}


def test_prompt_manager_returns_none_for_missing_or_empty_prompt(tmp_path):
    _write_prompt_config(
        tmp_path,
        """
prompts:
  empty_prompt: ""
""",
    )
    manager = PromptManager(config_dir=tmp_path)

    assert manager.get_prompt("unknown") is None
    assert manager.get_prompt("empty_prompt") == ""


def test_prompt_manager_reload_clears_cache_and_reloads_file(tmp_path):
    prompt_file = tmp_path / "api_clients" / "deepseek.yaml"
    _write_prompt_config(
        tmp_path,
        """
prompts:
  first: "one"
""",
    )
    manager = PromptManager(config_dir=tmp_path)
    assert manager.get_prompt("first") == "one"

    prompt_file.write_text(
        """
prompts:
  second: "two"
""",
        encoding="utf-8",
    )
    manager.reload()

    assert manager.get_prompt("first") is None
    assert manager.get_prompt("second") == "two"
