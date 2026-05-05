from pathlib import Path

from src.cli.category_handlers import (
    export_new_categories,
    handle_sync_giga_categories,
    handle_template_correction,
    handle_template_update,
    handle_update_mappings_from_csv,
)


class NonTty:
    def isatty(self):
        return False


class Tty:
    def isatty(self):
        return True


class TemplateService:
    def __init__(self, update_result=None, correction_result=None, error=None):
        self.update_result = update_result
        self.correction_result = correction_result
        self.error = error
        self.update_calls = []
        self.correction_calls = []

    def update_template_from_file(self, template_path, category_name):
        self.update_calls.append((template_path, category_name))
        if self.error:
            raise self.error
        return self.update_result

    def correct_rules_from_report(self, report_path, category_name):
        self.correction_calls.append((report_path, category_name))
        if self.error:
            raise self.error
        return self.correction_result


class CategoryService:
    def __init__(self, sync_result=None, update_result=None, error=None):
        self.sync_result = sync_result or {}
        self.update_result = update_result or {}
        self.error = error
        self.sync_calls = 0
        self.update_calls = []

    def sync_giga_categories(self):
        self.sync_calls += 1
        if self.error:
            raise self.error
        return self.sync_result

    def update_mappings_from_csv(self, csv_file_path):
        self.update_calls.append(csv_file_path)
        if self.error:
            raise self.error
        return self.update_result


def test_template_update_missing_file_prints_cancel(capsys):
    handle_template_update(db=object(), template_path="/missing/template.xlsm", category_name="CABINET")

    output = capsys.readouterr().out
    assert "文件路径和品类名称均不能为空" in output


def test_template_update_calls_service_and_prints_success(monkeypatch, capsys):
    service = TemplateService(update_result=(True, "saved"))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_update(
        db=object(),
        template_path="/tmp/template.xlsm",
        category_name="CABINET",
    )

    assert service.update_calls == [("/tmp/template.xlsm", "CABINET")]
    assert "✅ saved" in capsys.readouterr().out


def test_template_update_prints_failure_message(monkeypatch, capsys):
    service = TemplateService(update_result=(False, "not saved"))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_update(
        db=object(),
        template_path="/tmp/template.xlsm",
        category_name="CABINET",
    )

    assert "❌ not saved" in capsys.readouterr().out


def test_template_update_prompts_for_missing_arguments(monkeypatch):
    service = TemplateService(update_result=(True, "saved"))
    inputs = iter(['"/tmp/template.xlsm"', "CABINET"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_update(db=object())

    assert service.update_calls == [("/tmp/template.xlsm", "CABINET")]


def test_template_update_prints_errors(monkeypatch, capsys):
    service = TemplateService(error=RuntimeError("boom"))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_update(
        db=object(),
        template_path="/tmp/template.xlsm",
        category_name="CABINET",
    )

    assert "更新亚马逊类目模板时发生错误: boom" in capsys.readouterr().out


def test_template_correction_missing_file_prints_cancel(capsys):
    handle_template_correction(
        db=object(),
        report_path="/missing/report.xlsm",
        category_name="CABINET",
    )

    assert "文件路径和品类名称均不能为空" in capsys.readouterr().out


def test_template_correction_calls_service_and_prints_success(monkeypatch, capsys):
    service = TemplateService(correction_result=(True, "corrected"))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_correction(
        db=object(),
        report_path="/tmp/report.xlsm",
        category_name="CABINET",
    )

    assert service.correction_calls == [("/tmp/report.xlsm", "CABINET")]
    assert "✅ 完成" in capsys.readouterr().out


def test_template_correction_prints_failure(monkeypatch, capsys):
    service = TemplateService(correction_result=(False, "failed"))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_correction(
        db=object(),
        report_path="/tmp/report.xlsm",
        category_name="CABINET",
    )

    assert "❌ 失败" in capsys.readouterr().out


def test_template_correction_prints_errors(monkeypatch, capsys):
    service = TemplateService(error=RuntimeError("boom"))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_correction(
        db=object(),
        report_path="/tmp/report.xlsm",
        category_name="CABINET",
    )

    assert "执行模板规则矫正时发生错误: boom" in capsys.readouterr().out


def test_template_correction_prompts_for_missing_arguments(monkeypatch):
    service = TemplateService(correction_result=(True, "corrected"))
    inputs = iter(['"/tmp/report.xlsm"', "CABINET"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
    monkeypatch.setattr("src.cli.category_handlers.os.path.exists", lambda path: True)
    monkeypatch.setattr(
        "src.services.amz_template_management_service.TemplateManagementService",
        lambda db: service,
    )

    handle_template_correction(db=object())

    assert service.correction_calls == [("/tmp/report.xlsm", "CABINET")]


def test_sync_giga_categories_requires_auto_confirm_for_non_tty(monkeypatch, capsys):
    monkeypatch.setattr("src.cli.category_handlers.sys.stdin", NonTty())

    handle_sync_giga_categories(db=object(), auto_confirm=False)

    output = capsys.readouterr().out
    assert "自动确认" in output


def test_sync_giga_categories_cancels_when_tty_user_declines(monkeypatch, capsys):
    monkeypatch.setattr("src.cli.category_handlers.sys.stdin", Tty())
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    handle_sync_giga_categories(db=object(), auto_confirm=False)

    assert "操作已取消" in capsys.readouterr().out


def test_sync_giga_categories_runs_and_exports_when_requested(monkeypatch):
    service = CategoryService(
        sync_result={
            "inserted_count": 1,
            "new_category_list": [{"category_code": "CAB", "category_name": "Cabinet"}],
        }
    )
    exported = []
    monkeypatch.setattr(
        "src.services.category_maintenance_service.CategoryMaintenanceService",
        lambda db: service,
    )
    monkeypatch.setattr(
        "src.cli.category_handlers.export_new_categories",
        lambda categories: exported.extend(categories),
    )

    handle_sync_giga_categories(db=object(), auto_confirm=True, export=True)

    assert service.sync_calls == 1
    assert exported == [{"category_code": "CAB", "category_name": "Cabinet"}]


def test_sync_giga_categories_prompts_tty_for_export(monkeypatch):
    service = CategoryService(
        sync_result={
            "inserted_count": 1,
            "new_category_list": [{"category_code": "CAB", "category_name": "Cabinet"}],
        }
    )
    exported = []
    inputs = iter(["y"])
    monkeypatch.setattr("src.cli.category_handlers.sys.stdin", Tty())
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
    monkeypatch.setattr(
        "src.services.category_maintenance_service.CategoryMaintenanceService",
        lambda db: service,
    )
    monkeypatch.setattr(
        "src.cli.category_handlers.export_new_categories",
        lambda categories: exported.extend(categories),
    )

    handle_sync_giga_categories(db=object(), auto_confirm=True, export=False)

    assert exported == [{"category_code": "CAB", "category_name": "Cabinet"}]


def test_sync_giga_categories_skips_export_prompt_in_non_tty(monkeypatch, capsys):
    service = CategoryService(
        sync_result={
            "inserted_count": 1,
            "new_category_list": [{"category_code": "CAB", "category_name": "Cabinet"}],
        }
    )
    monkeypatch.setattr("src.cli.category_handlers.sys.stdin", NonTty())
    monkeypatch.setattr(
        "src.services.category_maintenance_service.CategoryMaintenanceService",
        lambda db: service,
    )

    handle_sync_giga_categories(db=object(), auto_confirm=True, export=False)

    assert "非交互模式，跳过导出 CSV 询问" in capsys.readouterr().out


def test_sync_giga_categories_prints_errors(monkeypatch, capsys):
    service = CategoryService(error=RuntimeError("boom"))
    monkeypatch.setattr(
        "src.services.category_maintenance_service.CategoryMaintenanceService",
        lambda db: service,
    )

    handle_sync_giga_categories(db=object(), auto_confirm=True)

    assert "品类同步失败: boom" in capsys.readouterr().out


def test_update_mappings_from_csv_empty_path_cancels(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    handle_update_mappings_from_csv(db=object())

    output = capsys.readouterr().out
    assert "未提供文件路径" in output


def test_update_mappings_from_csv_calls_service(monkeypatch, capsys):
    service = CategoryService(update_result={"updated_count": 2})
    monkeypatch.setattr(
        "src.services.category_maintenance_service.CategoryMaintenanceService",
        lambda db: service,
    )

    handle_update_mappings_from_csv(db=object(), csv_file_path="/tmp/map.csv")

    assert service.update_calls == ["/tmp/map.csv"]
    assert "从 CSV 批量更新品类映射" in capsys.readouterr().out


def test_update_mappings_from_csv_prints_errors(monkeypatch, capsys):
    service = CategoryService(error=RuntimeError("boom"))
    monkeypatch.setattr(
        "src.services.category_maintenance_service.CategoryMaintenanceService",
        lambda db: service,
    )

    handle_update_mappings_from_csv(db=object(), csv_file_path="/tmp/map.csv")

    assert "批量更新失败: boom" in capsys.readouterr().out


def test_export_new_categories_empty_list(capsys):
    export_new_categories([])

    output = capsys.readouterr().out
    assert "没有新品类需要导出" in output


def test_export_new_categories_writes_csv(monkeypatch, tmp_path, capsys):
    class FakePath:
        def __init__(self, value):
            self.value = Path(value)

        def resolve(self):
            return SimplePath(tmp_path)

    class SimplePath:
        def __init__(self, root):
            self.parents = [root / "src" / "cli", root / "src", root]

    monkeypatch.setattr("src.cli.category_handlers.Path", FakePath)
    monkeypatch.setattr(
        "src.cli.category_handlers.datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda: type("Now", (), {
                "strftime": staticmethod(lambda fmt: "20260505_120000")
            })())
        }),
    )

    export_new_categories([
        {"category_code": "CAB001", "category_name": "Cabinet"},
        {"category_code": "MIR001", "category_name": "Mirror"},
    ])

    output_file = tmp_path / "output" / "new_giga_categories_20260505_120000.csv"
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8-sig")
    assert "category_code,category_name,standard_category_name" in content
    assert "CAB001,Cabinet," in content
    assert "MIR001,Mirror," in content
    assert "新品类列表已导出到" in capsys.readouterr().out


def test_export_new_categories_prints_errors(monkeypatch, tmp_path, capsys):
    class FakePath:
        def __init__(self, value):
            self.value = value

        def resolve(self):
            return SimplePath(tmp_path)

    class SimplePath:
        def __init__(self, root):
            self.parents = [root / "src" / "cli", root / "src", root]

    monkeypatch.setattr("src.cli.category_handlers.Path", FakePath)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    export_new_categories([{"category_code": "CAB001", "category_name": "Cabinet"}])

    assert "导出失败: boom" in capsys.readouterr().out
