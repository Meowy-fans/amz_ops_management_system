import pytest
import sys
from unittest.mock import MagicMock
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Rule YAML writes to config/amz_listing_data_mapping/api_attribute_rules/ are blocked
# during pytest (see rule_yaml_write_guard). Use tmp_path config_dir on services under
# test, or set AMZ_ALLOW_RULE_YAML_WRITE=1 for intentional canonical writes.

@pytest.fixture
def mock_db_session():
    """Returns a mock SQLAlchemy Session"""
    session = MagicMock()
    return session

@pytest.fixture
def mock_llm_service():
    """Returns a mock LLM Service"""
    service = MagicMock()
    # Setup default return values if needed
    service.generate_content.return_value = "Mocked Content"
    return service
