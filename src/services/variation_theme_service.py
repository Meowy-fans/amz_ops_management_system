"""
Variation Theme Service
负责使用LLM判定变体主题和属性
"""
import logging
from typing import Dict, Any, List

from infrastructure.llm import get_llm_service, LLMRequest
from src.services.variation_theme_helpers import (
    build_correction_prompt,
    build_first_round_prompt,
    check_attribute_uniqueness,
    format_variation_attributes,
    strip_html,
)
from src.utils.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class VariationThemeService:
    """
    变体主题服务
    
    职责：
    - 使用LLM判定变体主题（如 Color, Size, Color/Size）
    - 为每个子SKU提取变体属性值
    - 验证属性唯一性
    - 失败时自动重试纠正
    """
    
    def __init__(self):
        """初始化服务"""
        self.llm_service = get_llm_service()
        self.prompt_manager = PromptManager()
        
        logger.info("VariationThemeService 初始化完成")
    
    def determine_variation_theme(
        self,
        family_data: List[Dict[str, Any]],
        valid_themes: List[str],
        priority_themes: List[str] = None
    ) -> Dict[str, Any]:
        """
        使用LLM判定变体主题和属性
        
        Args:
            family_data: 变体家族的完整数据列表，每个元素包含：
                {
                    'meow_sku': str,
                    'product_name': str,
                    'product_description': str,
                    'raw_data': dict,
                    'category_name': str
                }
            valid_themes: 有效的变体主题列表（从模板规则获取）
            priority_themes: 高优先级主题列表（可选）
        
        Returns:
            {
                'variation_theme': str,           # 如 'Color', 'Size', 'Color/Size'
                'child_attributes': {             # 每个子SKU的属性
                    'meow_sku_1': {'color_name': 'White', 'size_name': '36 inch'},
                    'meow_sku_2': {'color_name': 'Black', 'size_name': '36 inch'},
                    ...
                }
            }
        """
        logger.info(f"开始判定变体主题，家族包含 {len(family_data)} 个SKU")
        
        # 第一轮：初次判定
        result = self._first_round_determination(
            family_data,
            valid_themes,
            priority_themes or []
        )
        
        # 验证唯一性
        if self._check_attribute_uniqueness(result.get('child_attributes', {})):
            logger.info("✅ 变体属性唯一性验证通过")
            # 格式化属性（尺寸取整等）
            result['child_attributes'] = self._format_variation_attributes(
                result['child_attributes']
            )
            return result
        
        # 第二轮：纠正重复
        logger.warning("⚠️ 检测到重复属性，启动纠正流程...")
        corrected_result = self._second_round_correction(
            family_data,
            valid_themes,
            priority_themes or [],
            result.get('variation_theme', 'Color')
        )
        
        # 再次验证
        if not self._check_attribute_uniqueness(corrected_result.get('child_attributes', {})):
            logger.error("❌ 纠正后仍有重复，使用初次结果")
            corrected_result = result
        else:
            logger.info("✅ 纠正成功，属性唯一")
        
        # 格式化属性
        corrected_result['child_attributes'] = self._format_variation_attributes(
            corrected_result['child_attributes']
        )
        
        return corrected_result
    
    def _first_round_determination(
        self,
        family_data: List[Dict],
        valid_themes: List[str],
        priority_themes: List[str]
    ) -> Dict[str, Any]:
        """第一轮：使用LLM判定变体主题"""
        user_prompt = build_first_round_prompt(
            family_data,
            valid_themes,
            priority_themes,
        )
        
        # 获取Prompt
        system_prompt = self.prompt_manager.get_prompt('prod_variance_determ')
        if not system_prompt:
            logger.error("未找到 prod_variance_determ Prompt")
            return {'variation_theme': 'Color', 'child_attributes': {}}
        
        # 调用LLM
        try:
            request = LLMRequest(
                task_type='product_attribute_enrichment',
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_mode=True,
                temperature=0.7
            )
            
            response = self.llm_service.generate(request)
            result = response.content
            
            logger.info(f"第一轮LLM返回主题: {result.get('variation_theme')}")
            return result
            
        except Exception as e:
            logger.error(f"第一轮LLM调用失败: {e}")
            return {'variation_theme': 'Color', 'child_attributes': {}}
    
    def _second_round_correction(
        self,
        family_data: List[Dict],
        valid_themes: List[str],
        priority_themes: List[str],
        failed_theme: str
    ) -> Dict[str, Any]:
        """第二轮：纠正重复的变体属性"""
        user_prompt = build_correction_prompt(
            family_data,
            valid_themes,
            priority_themes,
            failed_theme,
        )
        
        # 获取Prompt
        system_prompt = self.prompt_manager.get_prompt('prod_variance_correction')
        if not system_prompt:
            logger.error("未找到 prod_variance_correction Prompt")
            return {'variation_theme': failed_theme, 'child_attributes': {}}
        
        # 调用LLM
        try:
            request = LLMRequest(
                task_type='product_attribute_enrichment',
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_mode=True,
                temperature=0.7
            )
            
            response = self.llm_service.generate(request)
            result = response.content
            
            logger.info(f"第二轮LLM返回主题: {result.get('variation_theme')}")
            return result
            
        except Exception as e:
            logger.error(f"第二轮LLM调用失败: {e}")
            return {'variation_theme': failed_theme, 'child_attributes': {}}
    
    @staticmethod
    def _check_attribute_uniqueness(child_attributes: Dict[str, Dict]) -> bool:
        """
        验证变体属性唯一性
        
        Args:
            child_attributes: {
                'sku1': {'color_name': 'White', 'size_name': '36'},
                'sku2': {'color_name': 'Black', 'size_name': '36'},
            }
        
        Returns:
            True: 所有属性组合唯一
            False: 存在重复
        """
        return check_attribute_uniqueness(child_attributes)
    
    @staticmethod
    def _format_variation_attributes(
        child_attributes: Dict[str, Dict]
    ) -> Dict[str, Dict]:
        """
        格式化变体属性
        
        主要处理：
        - 尺寸类属性取整（19.88 → 20）
        
        Args:
            child_attributes: 原始属性
        
        Returns:
            格式化后的属性
        """
        return format_variation_attributes(child_attributes)
    
    @staticmethod
    def _strip_html(html_string: str) -> str:
        """移除HTML标签"""
        return strip_html(html_string)
