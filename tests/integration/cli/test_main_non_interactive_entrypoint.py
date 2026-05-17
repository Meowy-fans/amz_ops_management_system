import pytest

import main as app_main
from src.cli.task_dispatcher import UnknownTaskError


class FakeSession:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append(("exit", exc_type))
        return False


def test_main_dispatches_non_interactive_task_and_closes_session(monkeypatch):
    events = []
    dispatch_calls = []

    monkeypatch.setattr(app_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(app_main.sys, "argv", [
        "main.py",
        "--task",
        "generate-listing",
        "--category",
        "CABINET",
        "--file",
        "/tmp/input.csv",
        "--auto-confirm",
    ])
    monkeypatch.setattr(app_main, "SessionLocal", lambda: FakeSession(events))

    def fake_dispatch(db, task, **kwargs):
        dispatch_calls.append((db, task, kwargs))

    monkeypatch.setattr(app_main, "dispatch_task", fake_dispatch)

    with pytest.raises(SystemExit) as exc_info:
        app_main.main()

    assert exc_info.value.code == 0
    assert events == ["enter", ("exit", None)]
    assert len(dispatch_calls) == 1
    db, task, kwargs = dispatch_calls[0]
    assert isinstance(db, FakeSession)
    assert task == "generate-listing"
    assert kwargs == {
        "category": "CABINET",
        "file_path": "/tmp/input.csv",
        "auto_confirm": True,
        "dry_run": True,
    }


def test_main_unknown_non_interactive_task_exits_with_usage_error(monkeypatch, capsys):
    events = []

    monkeypatch.setattr(app_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(app_main.sys, "argv", ["main.py", "--task", "missing-task"])
    monkeypatch.setattr(app_main, "SessionLocal", lambda: FakeSession(events))

    def fake_dispatch(db, task, **kwargs):
        raise UnknownTaskError(task)

    monkeypatch.setattr(app_main, "dispatch_task", fake_dispatch)

    with pytest.raises(SystemExit) as exc_info:
        app_main.main()

    assert exc_info.value.code == 2
    assert events == ["enter", ("exit", UnknownTaskError)]
    assert "未知任务: missing-task" in capsys.readouterr().out
