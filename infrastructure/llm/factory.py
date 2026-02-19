"""LLM服务工厂"""
import logging
from typing import Dict
from src.config.settings import settings
from infrastructure.llm.interface import LLMServiceInterface
from infrastructure.llm.implementations.direct_llm_service import DirectLLMService

logger = logging.getLogger(__name__)

_service_instance = None

def get_llm_service() -> LLMServiceInterface:
    """获取LLM服务单例"""
    global _service_instance
    
    if _service_instance is not None:
        return _service_instance
    
    # 从配置决定模式
    mode = settings.LLM_SERVICE_MODE
    
    if mode == 'autogen':
        from infrastructure.llm.implementations.autogen_llm_service import AutoGenLLMService
        _service_instance = AutoGenLLMService()
        logger.info("LLM服务初始化完成（AutoGen模式）")
    else:
        config = _load_direct_config()
        _service_instance = DirectLLMService(config)
        logger.info("LLM服务初始化完成（Direct模式）")
    
    return _service_instance

def _load_direct_config() -> Dict:
    """加载Direct模式配置"""
    return {
        'default_provider': settings.LLM_PROVIDER,
        'providers': {
            'deepseek': {
                'default_model': settings.DEEPSEEK_MODEL
            },
            'qwen': {
                'default_model': settings.QWEN_MODEL
            }
        },
        'task_routing': {
            'product_generation': settings.LLM_PROVIDER,
            'sku_mapping': 'qwen',
            'product_attribute_enrichment': settings.LLM_PROVIDER
        }
    }
