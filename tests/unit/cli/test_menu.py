from src.cli.menu import INTERACTIVE_TASK_CHOICES, run_interactive_menu


class DummySession:
    def __enter__(self):
        return "db"

    def __exit__(self, exc_type, exc, tb):
        return False


def test_interactive_menu_exit_does_not_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")

    run_interactive_menu(lambda: DummySession(), lambda db, task: calls.append((db, task)))

    assert calls == []


def test_interactive_menu_dispatches_selected_task(monkeypatch):
    inputs = iter(["1.7", "", "0"])
    calls = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    run_interactive_menu(lambda: DummySession(), lambda db, task: calls.append((db, task)))

    assert calls == [("db", "update-prices")]


def test_interactive_menu_reprompts_after_invalid_choice(monkeypatch, capsys):
    inputs = iter(["missing", "", "0"])
    calls = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    run_interactive_menu(lambda: DummySession(), lambda db, task: calls.append((db, task)))

    output = capsys.readouterr().out
    assert calls == []
    assert "无效的选项" in output


def test_interactive_menu_handles_keyboard_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    run_interactive_menu(lambda: DummySession(), lambda db, task: None)

    assert "程序被用户中断" in capsys.readouterr().out


def test_interactive_menu_handles_dispatch_errors(monkeypatch, capsys):
    inputs = iter(["1.7", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    def dispatch_error(db, task):
        raise RuntimeError(f"boom for {task}")

    run_interactive_menu(lambda: DummySession(), dispatch_error)

    output = capsys.readouterr().out
    assert "发生错误: boom for update-prices" in output


def test_interactive_task_choices_include_maintenance_placeholder():
    assert INTERACTIVE_TASK_CHOICES["4.1"] == "sku-sync-from-csv"
