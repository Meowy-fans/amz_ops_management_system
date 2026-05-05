from src.services.category_mapping_csv_updater import CategoryMappingCsvUpdater


class Reporter:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class Repository:
    def __init__(self, valid_categories=None, updated_count=0, error=None):
        self.valid_categories = valid_categories or {"cabinet", "home_mirror"}
        self.updated_count = updated_count
        self.error = error
        self.updates = []

    def get_valid_amazon_categories(self):
        return self.valid_categories

    def batch_update_category_mappings(self, updates):
        self.updates.append(updates)
        if self.error:
            raise self.error
        return self.updated_count


def make_updater(repository=None):
    reporter = Reporter()
    updater = CategoryMappingCsvUpdater(repository or Repository(), reporter)
    return updater, reporter


def write_csv(path, content):
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_update_mappings_from_csv_missing_file_returns_empty_result(tmp_path):
    updater, reporter = make_updater()

    result = updater.update_mappings_from_csv(str(tmp_path / "missing.csv"))

    assert result["updated_count"] == 0
    assert result["errors"] == [f"文件不存在: {tmp_path / 'missing.csv'}"]
    assert any("文件不存在" in message for message in reporter.messages)


def test_update_mappings_from_csv_read_failure(monkeypatch, tmp_path):
    csv_path = write_csv(tmp_path / "mappings.csv", "bad")
    updater, reporter = make_updater()
    monkeypatch.setattr(
        updater,
        "_read_csv",
        lambda path: (_ for _ in ()).throw(RuntimeError("cannot read")),
    )

    result = updater.update_mappings_from_csv(csv_path)

    assert result["errors"] == ["读取文件失败: cannot read"]
    assert any("读取文件失败" in message for message in reporter.messages)


def test_update_mappings_from_csv_empty_file(tmp_path):
    csv_path = write_csv(
        tmp_path / "empty.csv",
        "supplier_platform,supplier_category_code,standard_category_name\n",
    )
    updater, reporter = make_updater()

    result = updater.update_mappings_from_csv(csv_path)

    assert result == {
        "total_rows": 0,
        "valid_rows": 0,
        "invalid_rows": 0,
        "updated_count": 0,
        "errors": [],
    }
    assert any("文件为空" in message for message in reporter.messages)


def test_update_mappings_from_csv_returns_validation_errors(tmp_path):
    csv_path = write_csv(
        tmp_path / "invalid.csv",
        "\n".join([
            "supplier_platform,supplier_category_code,standard_category_name",
            ",CAB001,cabinet",
            "giga,,cabinet",
            "giga,CAB003,",
            "giga,CAB004,unknown",
        ]),
    )
    updater, reporter = make_updater()

    result = updater.update_mappings_from_csv(csv_path)

    assert result["total_rows"] == 4
    assert result["valid_rows"] == 0
    assert result["invalid_rows"] == 4
    assert "supplier_platform 为空" in result["errors"][0]
    assert "supplier_category_code 为空" in result["errors"][1]
    assert "standard_category_name 为空" in result["errors"][2]
    assert "不是有效的亚马逊品类" in result["errors"][3]
    assert any("没有有效数据可以更新" in message for message in reporter.messages)


def test_display_errors_truncates_after_ten_messages():
    updater, reporter = make_updater()

    updater._display_errors([f"error-{idx}" for idx in range(12)])

    assert any("error-0" in message for message in reporter.messages)
    assert any("还有 2 个错误" in message for message in reporter.messages)


def test_update_mappings_from_csv_success_with_partial_update_warning(tmp_path):
    csv_path = write_csv(
        tmp_path / "valid.csv",
        "\n".join([
            "supplier_platform,supplier_category_code,standard_category_name",
            "giga,CAB001,cabinet",
            "giga,MIR001,home_mirror",
        ]),
    )
    repository = Repository(updated_count=1)
    updater, reporter = make_updater(repository)

    result = updater.update_mappings_from_csv(csv_path)

    assert result["valid_rows"] == 2
    assert result["updated_count"] == 1
    assert repository.updates == [[
        {
            "supplier_platform": "giga",
            "supplier_category_code": "CAB001",
            "standard_category_name": "cabinet",
        },
        {
            "supplier_platform": "giga",
            "supplier_category_code": "MIR001",
            "standard_category_name": "home_mirror",
        },
    ]]
    assert any("部分记录未更新成功" in message for message in reporter.messages)


def test_update_mappings_from_csv_returns_update_errors(tmp_path):
    csv_path = write_csv(
        tmp_path / "valid.csv",
        "\n".join([
            "supplier_platform,supplier_category_code,standard_category_name",
            "giga,CAB001,cabinet",
        ]),
    )
    updater, reporter = make_updater(Repository(error=RuntimeError("db failed")))

    result = updater.update_mappings_from_csv(csv_path)

    assert result["valid_rows"] == 1
    assert result["updated_count"] == 0
    assert result["errors"] == ["更新失败: db failed"]
    assert any("更新失败: db failed" in message for message in reporter.messages)
