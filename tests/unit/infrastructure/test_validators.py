import pytest

from infrastructure.exceptions import AppException, ValidationException
from infrastructure.validators import validate_file_path


def test_app_exception_keeps_message_and_default_code():
    exc = AppException("failed")

    assert str(exc) == "failed"
    assert exc.message == "failed"
    assert exc.code == "APP_ERROR"


def test_validation_exception_uses_validation_error_code():
    exc = ValidationException("bad input")

    assert str(exc) == "bad input"
    assert exc.message == "bad input"
    assert exc.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("suffix", [".txt", ".csv", ".tsv", ".CSV"])
def test_validate_file_path_accepts_supported_existing_files(tmp_path, suffix):
    file_path = tmp_path / f"input{suffix}"
    file_path.write_text("content", encoding="utf-8")

    assert validate_file_path(f"  {file_path}  ") == str(file_path.absolute())


def test_validate_file_path_rejects_missing_path(tmp_path):
    missing_path = tmp_path / "missing.csv"

    with pytest.raises(ValidationException) as exc_info:
        validate_file_path(str(missing_path))

    assert "文件不存在" in str(exc_info.value)


def test_validate_file_path_rejects_directory(tmp_path):
    with pytest.raises(ValidationException) as exc_info:
        validate_file_path(str(tmp_path))

    assert "不是文件" in str(exc_info.value)


def test_validate_file_path_rejects_unsupported_suffix(tmp_path):
    file_path = tmp_path / "input.xlsx"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(ValidationException) as exc_info:
        validate_file_path(str(file_path))

    assert "不支持的格式: .xlsx" in str(exc_info.value)
