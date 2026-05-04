"""Variation mapping and priority-theme helpers for Amazon templates."""
import logging
from typing import Dict, List, Protocol

from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class PriorityThemeRepository(Protocol):
    def find_latest_priority_themes_by_category(self, category: str) -> List[str] | None:
        ...


INTERNAL_TO_AMZ_MAP = {
    "color_name": ["Color", "Color Name", "Main Color"],
    "size_name": ["Size", "Size Name", "Apparel Size", "Ring Size", "Shoe Size"],
    "material_name": ["Material", "Main Material", "Material Type"],
    "style_name": ["Style", "Style Name"],
    "item_package_quantity": ["Item Package Quantity", "Number Of Items"],
}

DEFAULT_PRIORITY_THEMES = [
    "COLOR/SIZE",
    "COLOR",
    "SIZE",
    "MATERIAL",
    "STYLE",
    "COLOR/STYLE",
]


def generate_variation_mapping(
    template_fields: List[str],
    variation_themes: List[str],
) -> Dict[str, str]:
    """Generate internal-to-template-field mapping for variation attributes."""
    variation_mapping = {}

    possible_variation_fields = set()
    for theme in variation_themes:
        parts = theme.split("/")
        possible_variation_fields.update(part.strip().lower() for part in parts)

    logger.info(
        f"从变体主题中识别出可能的变体属性字段 (小写): "
        f"{possible_variation_fields}"
    )

    template_fields_lower = {
        field.lower(): field
        for field in template_fields
    }

    for internal_key, amz_name_variations in INTERNAL_TO_AMZ_MAP.items():
        for amz_name in amz_name_variations:
            amz_name_lower = amz_name.lower()

            if (
                amz_name_lower in template_fields_lower
                and amz_name_lower in possible_variation_fields
            ):
                original_cased_field = template_fields_lower[amz_name_lower]
                variation_mapping[internal_key] = original_cased_field
                logger.info(
                    f"成功映射: 内部键 '{internal_key}' -> "
                    f"模板列 '{original_cased_field}'"
                )
                break

    logger.info(f"为该模板生成的最终 variation_mapping: {variation_mapping}")
    return variation_mapping


def parse_priority_theme_input(user_input: str) -> List[str]:
    """Parse comma-separated user input into normalized priority themes."""
    return [
        theme.strip().upper()
        for theme in user_input.split(",")
        if theme.strip()
    ]


def determine_priority_themes(
    category: str,
    repo: PriorityThemeRepository,
    reporter: ProgressReporter,
    input_func=None,
) -> List[str]:
    """Resolve priority themes from user input, history, or defaults."""
    input_func = input_func or input
    reporter.emit("\n--- 变体主题优先级配置 ---")
    reporter.emit("💡 请输入此品类的高优先级变体主题, 用逗号','分隔。")
    reporter.emit("   例如: COLOR/SIZE, COLOR, STYLE")
    reporter.emit("   直接按 Enter 键可跳过，系统将尝试自动沿用旧配置或使用默认值。")
    reporter.emit("请输入:")
    user_input = input_func().strip()

    if user_input:
        themes = parse_priority_theme_input(user_input)
        reporter.emit(f"✅ 已采纳您的输入: {themes}")
        return themes

    reporter.emit("ℹ️ 您已跳过输入。正在检查历史配置...")
    latest_themes = repo.find_latest_priority_themes_by_category(category)

    if latest_themes:
        reporter.emit(f"✅ 已成功沿用上个版本的配置: {latest_themes}")
        return latest_themes

    reporter.emit("⚠️ 未找到历史配置。将使用系统默认的高优先级列表。")
    reporter.emit(f"   默认列表为: {DEFAULT_PRIORITY_THEMES}")
    return DEFAULT_PRIORITY_THEMES
