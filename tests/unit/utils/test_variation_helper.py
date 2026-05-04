import pytest
from src.utils.variation_helper import VariationHelper

@pytest.fixture
def helper():
    return VariationHelper()

class TestFindVariationFamilies:
    def test_empty_input(self, helper):
        single, families = helper.find_variation_families([])
        assert single == []
        assert families == []

    def test_single_products_only(self, helper):
        data = [
            ('SKU-A', 'VENDOR-A', []),
            ('SKU-B', 'VENDOR-B', [])
        ]
        single, families = helper.find_variation_families(data)
        assert set(single) == {'SKU-A', 'SKU-B'}
        assert families == []

    def test_simple_family(self, helper):
        # A <-> B
        data = [
            ('SKU-A', 'VENDOR-A', ['VENDOR-B']),
            ('SKU-B', 'VENDOR-B', ['VENDOR-A'])
        ]
        single, families = helper.find_variation_families(data)
        assert single == []
        assert len(families) == 1
        assert set(families[0]) == {'SKU-A', 'SKU-B'}

    def test_complex_family_with_transitive_relation(self, helper):
        # A <-> B, B <-> C => A-B-C family
        data = [
            ('SKU-A', 'VENDOR-A', ['VENDOR-B']),
            ('SKU-B', 'VENDOR-B', ['VENDOR-A', 'VENDOR-C']),
            ('SKU-C', 'VENDOR-C', ['VENDOR-B'])
        ]
        single, families = helper.find_variation_families(data)
        assert single == []
        assert len(families) == 1
        assert set(families[0]) == {'SKU-A', 'SKU-B', 'SKU-C'}

    def test_mixed_products(self, helper):
        # Family: A-B, Single: C
        data = [
            ('SKU-A', 'VENDOR-A', ['VENDOR-B']),
            ('SKU-B', 'VENDOR-B', ['VENDOR-A']),
            ('SKU-C', 'VENDOR-C', [])
        ]
        single, families = helper.find_variation_families(data)
        assert single == ['SKU-C']
        assert len(families) == 1
        assert set(families[0]) == {'SKU-A', 'SKU-B'}

class TestFormatVariationAttributes:
    def test_empty_input(self, helper):
        assert helper.format_variation_attributes({}) == {}

    def test_rounding_size(self, helper):
        input_data = {
            'SKU-1': {'size_name': 19.88, 'other': 'val'},
            'SKU-2': {'size_with_text': '23.4'}
        }
        result = helper.format_variation_attributes(input_data)
        
        # 19.88 -> 20
        assert result['SKU-1']['size_name'] == '20'
        assert result['SKU-1']['other'] == 'val'
        
        # 23.4 -> 23
        assert result['SKU-2']['size_with_text'] == '23'

    def test_non_numeric_size_ignored(self, helper):
        input_data = {
            'SKU-1': {'size_name': 'Large'}
        }
        result = helper.format_variation_attributes(input_data)
        assert result['SKU-1']['size_name'] == 'Large'

class TestGeneralizeParentTitle:
    def test_empty_title(self, helper):
        assert helper.generalize_parent_title(None) is None
        assert helper.generalize_parent_title("") == ""

    def test_remove_suffix(self, helper):
        assert helper.generalize_parent_title("Modern Cabinet - White") == "Modern Cabinet"
        assert helper.generalize_parent_title("Vanity 24 Inch - Black") == "Vanity 24 Inch"

    def test_no_suffix_change(self, helper):
        assert helper.generalize_parent_title("Simple Cabinet") == "Simple Cabinet"
        
    def test_ignore_case(self, helper):
        assert helper.generalize_parent_title("Cabinet - white") == "Cabinet"
