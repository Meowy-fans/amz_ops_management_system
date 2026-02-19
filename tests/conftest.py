import pytest
import sys
from unittest.mock import MagicMock
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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
