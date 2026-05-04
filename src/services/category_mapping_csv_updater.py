"""CSV import workflow for supplier category mappings."""
import csv
import logging
import os
from typing import Dict

from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class CategoryMappingCsvUpdater:
    """Updates supplier category mappings from a CSV file."""

    def __init__(self, repository, reporter: ProgressReporter):
        self.repository = repository
        self.reporter = reporter

    def update_mappings_from_csv(self, csv_file_path: str) -> Dict:
        """Read, validate, and apply category mapping updates from CSV."""
        logger.info(f"Starting CSV import from: {csv_file_path}")
        self.reporter.emit("\n" + "=" * 70)
        self.reporter.emit("📥 从 CSV 文件更新品类映射")
        self.reporter.emit("=" * 70)

        if not os.path.exists(csv_file_path):
            error_msg = f"文件不存在: {csv_file_path}"
            self.reporter.emit(f"\n❌ {error_msg}")
            return self._empty_result([error_msg])

        self.reporter.emit(f"\n📁 文件路径: {csv_file_path}")
        self.reporter.emit("\n➡️ 步骤 1/4: 读取 CSV 文件...")

        try:
            rows = self._read_csv(csv_file_path)
            self.reporter.emit(f"✅ 读取到 {len(rows)} 行数据")
        except Exception as e:
            error_msg = f"读取文件失败: {e}"
            self.reporter.emit(f"\n❌ {error_msg}")
            return self._empty_result([error_msg])

        if not rows:
            self.reporter.emit("\n⚠️  文件为空，没有数据需要处理")
            return self._empty_result([])

        self.reporter.emit("\n➡️ 步骤 2/4: 验证亚马逊品类有效性...")
        valid_amazon_categories = self.repository.get_valid_amazon_categories()
        self.reporter.emit(f"✅ 系统中有 {len(valid_amazon_categories)} 个有效亚马逊品类")

        self.reporter.emit("\n➡️ 步骤 3/4: 验证数据...")
        valid_updates, errors = self._validate_rows(rows, valid_amazon_categories)

        self.reporter.emit("✅ 验证完成")
        self.reporter.emit(f"   有效行数: {len(valid_updates)}")
        self.reporter.emit(f"   无效行数: {len(errors)}")
        self._display_errors(errors)

        if not valid_updates:
            self.reporter.emit("\n❌ 没有有效数据可以更新")
            return {
                "total_rows": len(rows),
                "valid_rows": 0,
                "invalid_rows": len(errors),
                "updated_count": 0,
                "errors": errors,
            }

        return self._apply_updates(rows, valid_updates, errors)

    @staticmethod
    def _read_csv(csv_file_path: str):
        with open(csv_file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)

    @staticmethod
    def _validate_rows(rows, valid_amazon_categories):
        valid_updates = []
        errors = []

        for i, row in enumerate(rows, 1):
            supplier_platform = row.get("supplier_platform", "").strip()
            supplier_category_code = row.get("supplier_category_code", "").strip()
            standard_category_name = row.get("standard_category_name", "").strip()

            if not supplier_platform:
                errors.append(f"第 {i} 行: supplier_platform 为空")
                continue

            if not supplier_category_code:
                errors.append(f"第 {i} 行: supplier_category_code 为空")
                continue

            if not standard_category_name:
                errors.append(f"第 {i} 行: standard_category_name 为空")
                continue

            if standard_category_name.lower() not in valid_amazon_categories:
                errors.append(
                    f"第 {i} 行: standard_category_name '{standard_category_name}' "
                    f"不是有效的亚马逊品类"
                )
                continue

            valid_updates.append({
                "supplier_platform": supplier_platform,
                "supplier_category_code": supplier_category_code,
                "standard_category_name": standard_category_name,
            })

        return valid_updates, errors

    def _display_errors(self, errors):
        if not errors:
            return

        self.reporter.emit("\n⚠️  发现以下错误:")
        for error in errors[:10]:
            self.reporter.emit(f"   - {error}")
        if len(errors) > 10:
            self.reporter.emit(f"   ... 还有 {len(errors) - 10} 个错误")

    def _apply_updates(self, rows, valid_updates, errors):
        self.reporter.emit("\n➡️ 步骤 4/4: 更新数据库...")

        try:
            updated_count = self.repository.batch_update_category_mappings(valid_updates)
            self.reporter.emit(f"✅ 成功更新 {updated_count} 条记录")
            self._display_result_summary(rows, valid_updates, errors, updated_count)

            logger.info(f"CSV import completed: {updated_count} records updated")
            return {
                "total_rows": len(rows),
                "valid_rows": len(valid_updates),
                "invalid_rows": len(errors),
                "updated_count": updated_count,
                "errors": errors,
            }

        except Exception as e:
            error_msg = f"更新失败: {e}"
            self.reporter.emit(f"\n❌ {error_msg}")
            logger.error(error_msg, exc_info=True)
            return {
                "total_rows": len(rows),
                "valid_rows": len(valid_updates),
                "invalid_rows": len(errors),
                "updated_count": 0,
                "errors": errors + [error_msg],
            }

    def _display_result_summary(self, rows, valid_updates, errors, updated_count):
        self.reporter.emit("\n" + "=" * 70)
        self.reporter.emit("📊 更新完成统计")
        self.reporter.emit("=" * 70)
        self.reporter.emit(f"CSV 总行数:        {len(rows)}")
        self.reporter.emit(f"验证通过行数:      {len(valid_updates)}")
        self.reporter.emit(f"验证失败行数:      {len(errors)}")
        self.reporter.emit(f"成功更新记录:      {updated_count}")
        self.reporter.emit("=" * 70)

        if updated_count < len(valid_updates):
            self.reporter.emit("\n⚠️  注意: 部分记录未更新成功")
            self.reporter.emit("   可能原因: supplier_platform 和 supplier_category_code 组合不存在")

    @staticmethod
    def _empty_result(errors):
        return {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "updated_count": 0,
            "errors": errors,
        }
