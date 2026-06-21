"""Unit tests for attribute extraction LLM adapter."""

from src.services.attribute_extraction_llm_client import AttributeExtractionLLMClient


class Response:
    def __init__(self, content):
        self.content = content


class FakeLLMService:
    def __init__(self, content):
        self.content = content
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return Response(self.content)


def test_attribute_extraction_client_sends_json_mode_request():
    llm = FakeLLMService('{"value": "Track", "evidence": "track arms", "confidence": "medium"}')
    client = AttributeExtractionLLMClient(llm_service=llm)

    result = client.extract_attribute(
        {
            "sku": "SKU1",
            "product_type": "SOFA",
            "attribute": "arm",
            "title": "Sofa with track arms",
        }
    )

    assert result == {
        "value": "Track",
        "evidence": "track arms",
        "confidence": "medium",
    }
    assert llm.requests[0].task_type == "product_attribute_extraction"
    assert llm.requests[0].json_mode is True


def test_attribute_extraction_client_extracts_json_from_wrapped_text():
    llm = FakeLLMService('Result: {"value": null, "evidence": "", "confidence": "low"}')
    client = AttributeExtractionLLMClient(llm_service=llm)

    result = client.extract_attribute({"attribute": "room_type"})

    assert result == {"value": None, "evidence": "", "confidence": "low"}
