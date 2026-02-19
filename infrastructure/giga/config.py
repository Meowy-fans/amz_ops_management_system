"""Giga API配置管理"""
from typing import Dict
from src.config.settings import settings

class GigaConfig:
    """Giga API配置"""
    
    BASE_URL = settings.GIGA_BASE_URL
    CLIENT_ID = settings.GIGA_CLIENT_ID
    CLIENT_SECRET = settings.GIGA_CLIENT_SECRET
    
    ENDPOINTS = {
        'token': '/api-auth-v1/oauth/token',
        'product_list': '/api-b2b-v1/product/skus',
        'product_details': '/api-b2b-v1/product/detailInfo',
        'product_price': '/api-b2b-v1/product/price',
        'inventory_qty': '/api-b2b-v1/product/quantity',
    }
    
    @classmethod
    def validate(cls) -> bool:
        """验证配置完整性"""
        if not cls.CLIENT_ID or not cls.CLIENT_SECRET:
            raise ValueError("Giga API凭证未配置，请检查.env文件中的GIGA_CLIENT_ID和GIGA_CLIENT_SECRET")
        return True
    
    @classmethod
    def get_endpoint_url(cls, endpoint_name: str) -> str:
        """获取完整端点URL"""
        if endpoint_name not in cls.ENDPOINTS:
            raise ValueError(f"未知端点: {endpoint_name}")
        return f"{cls.BASE_URL}{cls.ENDPOINTS[endpoint_name]}"
