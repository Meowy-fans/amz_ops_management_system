"""
Data Mapping Helper
处理产品数据到Amazon字段的映射逻辑
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from src.utils.data_field_mapper import DataFieldMapper
from src.utils.data_mapping_llm import enrich_product_attributes
from src.utils.data_mapping_tasks import collect_llm_tasks_from_mapping
from src.utils.data_mapping_valid_values import align_to_valid_values, fuzzy_select, normalize_text

logger = logging.getLogger(__name__)


class DataMappingHelper:
    """
    数据映射助手
    
    职责：
    - 加载和解析 amz_mapping.json 配置
    - 执行各种类型的字段映射（static, direct, jsonb等）
    - 集成LLM增强字段
    - 提供统一的映射接口
    """
    
    WEIGHT_UNIT_MAP = DataFieldMapper.WEIGHT_UNIT_MAP
    DIMENSION_UNIT_MAP = DataFieldMapper.DIMENSION_UNIT_MAP
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化映射助手
        
        Args:
            config_path: 配置文件路径，默认自动查找项目根目录
        """
        if config_path is None:
            config_path = self._find_config_path()
        
        self.config_path = config_path
        self.mapping_config = self._load_mapping_config()
        self.field_mapper = DataFieldMapper()
        
        logger.info(f"数据映射助手初始化完成，加载 {len(self.mapping_config)} 个字段映射规则")
    
    def _find_config_path(self) -> Path:
        """查找配置文件路径"""
        # 方法1: 从当前文件向上查找项目根目录
        current = Path(__file__).resolve()
        
        for parent in current.parents:
            config_file = parent / "config" / "amz_listing_data_mapping" / "amz_mapping.json"
            if config_file.exists():
                return config_file
        
        # 方法2: 尝试相对于src目录
        src_dir = Path(__file__).resolve().parent.parent  # 从 src/utils 到 src
        project_root = src_dir.parent  # 从 src 到项目根
        config_file = project_root / "config" / "amz_listing_data_mapping" / "amz_mapping.json"
        
        if config_file.exists():
            return config_file
        
        # 方法3: 如果测试从项目根运行
        config_file = Path("config/amz_listing_data_mapping/amz_mapping.json")
        if config_file.exists():
            return config_file.resolve()
        
        raise FileNotFoundError(
            f"未找到 amz_mapping.json 配置文件\n"
            f"当前文件: {Path(__file__)}\n"
            f"尝试路径: {config_file}"
        )
    
    def _load_mapping_config(self) -> Dict:
        """加载映射配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                return config_data.get("mappings", {})
        except Exception as e:
            logger.error(f"❌ 加载映射配置失败: {e}")
            raise
    
    def apply_mapping(
        self,
        product_data: Dict[str, Any],
        template_rules: Dict[str, Any],
        category_map: Optional[Dict] = None,
        llm_service = None  # LLM服务实例（可选）
    ) -> Dict[str, Any]:
        """
        应用映射规则到产品数据
        
        Args:
            product_data: 产品原始数据，包含：
                - meow_sku
                - vendor_sku
                - category_name
                - product_name
                - product_description
                - selling_point_1~5
                - raw_data (JSONB)
                - final_price
                - total_quantity
            template_rules: 模板规则，包含：
                - valid_values
                - variation_mapping
            category_map: 品类映射配置（可选）
            llm_service: LLM服务实例（可选，用于增强字段）
                
        Returns:
            映射后的字段字典
        """
        if not product_data:
            return {}
        
        raw_data = product_data.get("raw_data", {}) or {}
        mapped_data = {}
        llm_tasks = []  # 收集LLM任务
        
        # 第一轮：处理非LLM字段
        for field_name, rule in self.mapping_config.items():
            source_type = rule.get("source_type")
            
            # 收集LLM增强任务
            if source_type == "llm_enhanced":
                llm_tasks.append({
                    "field_name": field_name,
                    "description": rule.get("description", ""),
                    "output_type": rule.get("output_type", "string")
                })
                continue
            
            # 跳过field_reference，稍后处理
            if source_type == "field_reference":
                continue
            
            value = self._map_single_field(
                field_name, rule, product_data, raw_data, category_map
            )
            
            if value is not None:
                mapped_data[field_name] = value
        
        # 第二轮：处理field_reference
        for field_name, rule in self.mapping_config.items():
            if rule.get("source_type") == "field_reference":
                referenced_field = rule.get("field")
                if referenced_field in mapped_data:
                    mapped_data[field_name] = mapped_data[referenced_field]

        # 第三轮：与模板有效值对齐（模糊匹配）
        mapped_data = align_to_valid_values(mapped_data, template_rules)

        # 第四轮：处理LLM增强字段
        if llm_tasks and llm_service:
            try:
                enriched_data = self._enrich_with_llm(
                    product_data,
                    llm_tasks,
                    template_rules,
                    llm_service
                )
                mapped_data.update(enriched_data)
                logger.debug(f"LLM增强完成，添加 {len(enriched_data)} 个字段")
            except Exception as e:
                logger.error(f"LLM增强失败: {e}")

        logger.debug(f"映射完成，生成 {len(mapped_data)} 个字段")
        return mapped_data
    
    def _enrich_with_llm(
        self,
        product_data: Dict[str, Any],
        llm_tasks: List[Dict],
        template_rules: Dict,
        llm_service
    ) -> Dict[str, Any]:
        """
        使用LLM增强产品属性
        
        Args:
            product_data: 产品原始数据
            llm_tasks: LLM任务列表
            template_rules: 模板规则
            llm_service: LLM服务实例
        """
        return enrich_product_attributes(
            product_data,
            llm_tasks,
            template_rules,
            llm_service,
            self._strip_html,
        )
    
    @staticmethod
    def _strip_html(html_string: Optional[str]) -> str:
        """移除HTML标签"""
        if not html_string:
            return ""
        clean_text = re.sub(r'<[^>]+>', '', html_string)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        return clean_text
    
    def _map_single_field(
        self,
        field_name: str,
        rule: Dict,
        product_data: Dict,
        raw_data: Dict,
        category_map: Optional[Dict]
    ) -> Any:
        """映射单个字段"""
        return self.field_mapper.map_single_field(
            field_name,
            rule,
            product_data,
            raw_data,
            category_map,
        )
    
    def _get_jsonb_value(self, raw_data: Dict, json_path: str) -> Any:
        """从JSONB中提取值"""
        return self.field_mapper.get_jsonb_value(raw_data, json_path)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return normalize_text(text)

    @staticmethod
    def _fuzzy_select(value: str, candidates: List[str], cutoff: float = 0.9) -> Optional[str]:
        return fuzzy_select(value, candidates, cutoff)
    
    def _map_unit(self, unit_type: str, raw_data: Dict) -> Optional[str]:
        """映射单位"""
        return self.field_mapper.map_unit(unit_type, raw_data)
    
    def _calculate_weight(self, weight_type: str, raw_data: Dict) -> Optional[float]:
        """计算重量"""
        return self.field_mapper.calculate_weight(weight_type, raw_data)
    
    def get_llm_tasks(self, template_rules: Dict) -> List[Dict]:
        """
        提取需要LLM处理的字段任务
        
        Args:
            template_rules: 模板规则
            
        Returns:
            LLM任务列表，每个任务包含：
            {
                'field_name': 字段名,
                'description': 任务描述,
                'output_type': 输出类型,
                'valid_options': 有效选项（可选）
            }
        """
        return collect_llm_tasks_from_mapping(self.mapping_config, template_rules)
