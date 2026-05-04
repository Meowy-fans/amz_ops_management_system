from src.cli.category_handlers import (
    export_new_categories,
    handle_sync_giga_categories,
    handle_template_update,
    handle_update_mappings_from_csv,
)


class NonTty:
    def isatty(self):
        return False


def test_template_update_missing_file_prints_cancel(capsys):
    handle_template_update(db=object(), template_path="/missing/template.xlsm", category_name="CABINET")

    output = capsys.readouterr().out
    assert "文件路径和品类名称均不能为空" in output


def test_sync_giga_categories_requires_auto_confirm_for_non_tty(monkeypatch, capsys):
    monkeypatch.setattr("src.cli.category_handlers.sys.stdin", NonTty())

    handle_sync_giga_categories(db=object(), auto_confirm=False)

    output = capsys.readouterr().out
    assert "自动确认" in output


def test_update_mappings_from_csv_empty_path_cancels(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    handle_update_mappings_from_csv(db=object())

    output = capsys.readouterr().out
    assert "未提供文件路径" in output


def test_export_new_categories_empty_list(capsys):
    export_new_categories([])

    output = capsys.readouterr().out
    assert "没有新品类需要导出" in output
