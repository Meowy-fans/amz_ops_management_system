import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch, call
from sqlalchemy.orm import Session
from src.services.pricing_service import NullPricingProgressReporter, PricingService

class TestPricingService:
    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_repo(self):
        with patch('src.services.pricing_service.PricingRepository') as MockRepo:
            yield MockRepo.return_value

    @pytest.fixture
    def mock_category_service(self):
        with patch('src.services.pricing_service.CategoryService') as MockCatService:
            yield MockCatService.return_value

    @pytest.fixture
    def mock_config_loader(self):
        with patch('src.services.pricing_service.PricingConfigLoader') as MockLoader:
            yield MockLoader

    @pytest.fixture
    def service(self, mock_db, mock_repo, mock_category_service):
        return PricingService(mock_db)

    def test_calculate_price_valid(self, service):
        pc = Decimal('100.00')
        lf = Decimal('20.00')
        # price = (100+20) * (1+0.01+0.05) / (1 - 0.15 - 0.10 - 0.05 - 0.20)
        # price = 120 * 1.06 / 0.50 = 127.2 / 0.5 = 254.40
        params = {
            'commission_rate': 0.15,
            'return_rate': 0.05,
            'settlement_cost_rate': 0.05,
            'ad_cost_rate': 0.10,
            'logistic_protection_rate': 0.01,
            'target_margin_rate': 0.20
        }
        
        price = service._calculate_price(pc, lf, params)
        assert price == Decimal('254.40')

    def test_calculate_price_invalid_denominator(self, service):
        pc = Decimal('100')
        lf = Decimal('20')
        # Sum of rates = 1.0 -> denominator = 0
        params = {
            'commission_rate': 0.5,
            'return_rate': 0.0,
            'settlement_cost_rate': 0.0,
            'ad_cost_rate': 0.0,
            'logistic_protection_rate': 0.0,
            'target_margin_rate': 0.5
        }
        
        with pytest.raises(ValueError):
            service._calculate_price(pc, lf, params)

    def test_update_prices_success(self, service, mock_repo, mock_category_service, mock_config_loader):
        # 1. Mock SKUs
        mock_repo.get_all_meow_skus.return_value = ['SKU1', 'SKU2']
        
        # 2. Mock Categories
        mock_category_service.categorize_skus.return_value = (
            {'CAT1': ['SKU1'], 'CAT2': ['SKU2']}, 
            [] # uncategorized
        )
        
        # 3. Mock Costs
        mock_repo.get_costs_for_skus.return_value = {
            'SKU1': (Decimal('100'), Decimal('10')),
            'SKU2': (Decimal('50'), Decimal('5'))
        }
        
        # 4. Mock Config Params
        mock_config_loader.get_params_for_category.return_value = {
            'commission_rate': 0.1,
            'return_rate': 0.0,
            'settlement_cost_rate': 0.0,
            'ad_cost_rate': 0.0,
            'logistic_protection_rate': 0.0,
            'target_margin_rate': 0.1,
            'formula_version': 'v1'
        }
        # Denom = 1 - 0.1 - 0 - 0 - 0.1 = 0.8
        # SKU1: (110) * 1.0 / 0.8 = 137.50
        # SKU2: (55) * 1.0 / 0.8 = 68.75
        
        total, success, report = service.update_prices()
        
        assert total == 2
        assert success == 2
        assert len(report) == 2
        
        # Verify Upsert Call
        # args[0] is the list of dicts
        call_args = mock_repo.upsert_final_prices.call_args[0][0]
        assert len(call_args) == 2
        assert call_args[0]['meow_sku'] == 'SKU1'
        assert call_args[0]['final_price'] == Decimal('137.50')
        assert call_args[1]['meow_sku'] == 'SKU2'
        assert call_args[1]['final_price'] == Decimal('68.75')

    def test_update_prices_missing_costs(self, service, mock_repo, mock_category_service, mock_config_loader):
        mock_repo.get_all_meow_skus.return_value = ['SKU1', 'SKU2']
        mock_category_service.categorize_skus.return_value = ({}, ['SKU1', 'SKU2'])
        
        # Costs only for SKU1
        mock_repo.get_costs_for_skus.return_value = {
            'SKU1': (Decimal('100'), Decimal('10'))
        }
        
        mock_config_loader.get_params_for_category.return_value = {
            'commission_rate': 0.1, 'return_rate': 0, 'settlement_cost_rate': 0,
            'ad_cost_rate': 0, 'logistic_protection_rate': 0, 'target_margin_rate': 0.1
        }
        
        total, success, report = service.update_prices()
        
        assert total == 2
        assert success == 1
        assert len(report) == 1
        assert report[0]['meow_sku'] == 'SKU1'

    def test_update_prices_with_null_reporter_does_not_print(
        self,
        mock_db,
        mock_repo,
        mock_category_service,
        capsys,
    ):
        service = PricingService(mock_db, reporter=NullPricingProgressReporter())
        mock_repo.get_all_meow_skus.return_value = []

        assert service.update_prices() == (0, 0, [])
        assert capsys.readouterr().out == ""
