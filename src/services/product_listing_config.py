"""Configuration helpers for product listing generation."""
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def find_default_category_config_path(start_file: str) -> Optional[Path]:
    """Find the default category mapping config from a module file path."""
    try:
        current = Path(start_file).resolve()
        for parent in current.parents:
            config_file = (
                parent
                / "config"
                / "amz_listing_data_mapping"
                / "category_mapping.json"
            )
            if config_file.exists():
                return config_file
    except Exception:
        return None

    return None


def load_category_config(
    config_path: Optional[Path],
    start_file: str,
) -> Optional[Dict]:
    """Load category_details from the Amazon listing category config."""
    if config_path is None:
        config_path = find_default_category_config_path(start_file)

    if config_path and config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                config = json.load(file)
                return config.get("category_details", {})
        except Exception as exc:
            logger.warning(f"加载品类配置失败: {exc}")
            return None

    return None
