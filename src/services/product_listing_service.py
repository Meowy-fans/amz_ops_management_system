"""
Product Listing Service
产品发品服务，整合所有Repository和Helper
"""
import logging
import uuid
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session

from src.repositories.product_listing_repository import ProductListingRepository
from src.repositories.product_data_repository import ProductDataRepository
from src.repositories.amz_template_repository import AmzTemplateRepository
from src.repositories.amz_listing_log_repository import AmzListingLogRepository
from src.services.product_listing_config import load_category_config
from src.services.product_listing_flow_helpers import (
    failure_result,
    get_pending_skus_for_category,
    success_result,
)
from src.services.product_listing_log_builder import build_listing_logs
from src.services.product_listing_variation_builder import ProductListingVariationBuilder
from src.utils.data_mapping_helper import DataMappingHelper
from src.utils.excel_generator import ExcelGenerator
from src.utils.variation_helper import VariationHelper

logger = logging.getLogger(__name__)


class ProductListingService:
    """
    产品发品服务
    
    职责：
    - 协调所有Repository和Helper
    - 实现完整的发品流程
    - 处理单品和变体的不同逻辑
    - 集成LLM增强功能
    """
    
    def __init__(
        self,
        db: Session,
        mapping_config_path: Optional[Path] = None,
        category_config_path: Optional[Path] = None
    ):
        """
        初始化服务
        
        Args:
            db: 数据库Session
            mapping_config_path: 映射配置文件路径
            category_config_path: 品类配置文件路径
        """
        # 初始化所有Repository
        self.product_listing_repo = ProductListingRepository(db)
        self.product_data_repo = ProductDataRepository(db)
        self.template_repo = AmzTemplateRepository(db)
        self.listing_log_repo = AmzListingLogRepository(db)
        
        # 初始化所有Helper
        self.data_mapper = DataMappingHelper(config_path=mapping_config_path)
        self.excel_generator = ExcelGenerator()
        self.variation_helper = VariationHelper()
        
        # 加载品类配置（如果提供）
        self.category_config = self._load_category_config(category_config_path)
        
        # 初始化LLM服务
        try:
            from infrastructure.llm import get_llm_service
            self.llm_service = get_llm_service()
            logger.info("LLM服务初始化成功")
        except Exception as e:
            logger.warning(f"LLM服务初始化失败: {e}，将跳过LLM增强字段")
            self.llm_service = None
        
        # 初始化变体主题服务
        try:
            from src.services.variation_theme_service import VariationThemeService
            self.variation_theme_service = VariationThemeService()
            logger.info("变体主题服务初始化成功")
        except Exception as e:
            logger.warning(f"变体主题服务初始化失败: {e}")
            self.variation_theme_service = None
        
        self.db = db
        
        logger.info("ProductListingService 初始化完成")
    
    def _load_category_config(self, config_path: Optional[Path]) -> Optional[Dict]:
        """加载品类配置"""
        return load_category_config(config_path, __file__)
    
    # ── shared row generation ─────────────────────────────────────

    def _build_rows_for_category(self, category_name: str):
        """Shared pipeline: SKU selection, variation detection, field mapping.

        Returns (all_rows, variation_logs, single_skus, variation_families)
        or raises ValueError when no pending SKUs or no template rules.
        """
        pending_skus, failure_message = get_pending_skus_for_category(
            self.product_listing_repo,
            category_name,
        )
        if failure_message:
            raise ValueError(failure_message)

        variation_data = self.product_listing_repo.get_variation_data(pending_skus)
        single_skus, variation_families = self.variation_helper.find_variation_families(
            variation_data
        )
        logger.info("单品: %d, 变体家族: %d", len(single_skus), len(variation_families))

        template_rules = self.template_repo.find_template_by_category(category_name)
        if not template_rules:
            raise ValueError(f"品类 '{category_name}' 没有模板规则")

        single_rows = self._process_single_products(single_skus, template_rules)
        variation_rows, variation_logs = self._process_variations(
            variation_families, template_rules
        )
        all_rows = single_rows + variation_rows

        if not all_rows:
            raise ValueError("没有生成任何数据行")

        logger.info("总共生成 %d 行数据", len(all_rows))
        return all_rows, variation_logs, single_skus, variation_families

    # ── Excel output path (preserved) ─────────────────────────────

    def generate_listings_by_category(self, category_name: str) -> Dict[str, Any]:
        """按品类生成发品 Excel 文件（现有路径，不变）。"""
        try:
            logger.info("开始生成品类 '%s' 的发品文件", category_name)
            batch_id = uuid.uuid4()

            all_rows, variation_logs, single_skus, variation_families = (
                self._build_rows_for_category(category_name)
            )

            excel_file = self.excel_generator.generate_excel(
                rows_data=all_rows,
                category_name=category_name,
                batch_id=batch_id,
            )
            self._save_listing_logs(single_skus, variation_logs, batch_id)
            self.db.commit()

            logger.info("发品 Excel 生成成功")
            return success_result(
                batch_id=batch_id,
                excel_file=excel_file,
                single_count=len(single_skus),
                variation_count=len(variation_families),
                total_rows=len(all_rows),
            )

        except ValueError as e:
            return failure_result(str(e))
        except Exception as e:
            self.db.rollback()
            logger.error("生成发品文件失败: %s", e, exc_info=True)
            return failure_result(f"生成失败: {str(e)}")

    # ── SP-API output path (new) ──────────────────────────────────

    def generate_listings_via_api(
        self,
        category_name: str,
        dry_run: bool = True,
        validation_only: bool = False,
    ) -> Dict[str, Any]:
        """按品类生成发品并提交到 Amazon SP-API。

        Args:
            category_name: 品类名称 (CABINET, HOME_MIRROR).
            dry_run: True 时仅构建 JSON payload 不提交.
            validation_only: True 时使用 VALIDATION_PREVIEW 模式.

        Returns:
            {"success": bool, "results": [...], "excel_file": None|str}
        """
        try:
            logger.info(
                "开始 SP-API 发品 category=%s dry_run=%s", category_name, dry_run
            )

            all_rows, variation_logs, single_skus, _vf = (
                self._build_rows_for_category(category_name)
            )

            # Map Excel-format rows to SP-API JSON attributes
            from src.utils.amazon_attribute_mapper import AmazonAttributeMapper

            mapper = AmazonAttributeMapper(product_type=category_name.upper())
            plans = mapper.map_rows_to_plans(all_rows)

            # Submit via Listings Items API
            from src.services.amazon_listing_submitter import AmazonListingSubmitter

            submitter = AmazonListingSubmitter(db=self.db)
            results = submitter.submit(
                plans,
                dry_run=dry_run,
                validation_only=validation_only,
            )

            # Also save listing logs for audit
            batch_id = uuid.uuid4()
            self._save_listing_logs(single_skus, variation_logs, batch_id)
            self.db.commit()

            return {
                "success": True,
                "results": results,
                "excel_file": None,
                "message": (
                    f"DRY RUN: {len(results)} payloads generated"
                    if dry_run
                    else f"Submitted {len(results)} listings"
                ),
            }

        except ValueError as e:
            return {"success": False, "results": [], "message": str(e)}
        except Exception as e:
            self.db.rollback()
            logger.error("SP-API 发品失败: %s", e, exc_info=True)
            return {"success": False, "results": [], "message": str(e)}
    
    def _process_single_products(
        self,
        meow_skus: List[str],
        template_rules: Dict
    ) -> List[Dict[str, Any]]:
        """
        处理单品
        
        Args:
            meow_skus: 单品的meow_sku列表
            template_rules: 模板规则
        
        Returns:
            数据行列表
        """
        rows = []
        
        for meow_sku in meow_skus:
            try:
                # 获取产品数据
                product_data = self.product_data_repo.get_full_product_data(meow_sku)
                
                if not product_data:
                    logger.warning(f"  跳过SKU {meow_sku}: 无数据")
                    continue
                
                # 应用映射（传入LLM服务）
                mapped_data = self.data_mapper.apply_mapping(
                    product_data,
                    template_rules,
                    self.category_config,
                    self.llm_service
                )
                
                # 添加单品特定字段
                mapped_data['Listing Action'] = 'Create or Replace (Full Update)'
                
                rows.append(mapped_data)
                
            except Exception as e:
                logger.error(f"  处理单品 {meow_sku} 失败: {e}")
                continue
        
        logger.info(f"  成功处理 {len(rows)}/{len(meow_skus)} 个单品")
        return rows
    
    def _process_variations(
        self,
        families: List[List[str]],
        template_rules: Dict
    ) -> Tuple[List[Dict[str, Any]], List[Dict]]:
        """
        处理变体家族
        
        Args:
            families: 变体家族列表
            template_rules: 模板规则
        
        Returns:
            (数据行列表, 日志数据列表)
        """
        return self._variation_builder().process_variations(families, template_rules)
    
    def _process_single_family(
        self,
        family_skus: List[str],
        template_rules: Dict
    ) -> Tuple[List[Dict[str, Any]], List[Dict]]:
        """处理单个变体家族"""
        return self._variation_builder().process_single_family(family_skus, template_rules)
    
    def _extract_valid_themes(self, template_rules: Dict) -> List[str]:
        """
        从模板规则中提取有效的变体主题列表
        
        Args:
            template_rules: 模板规则
        
        Returns:
            有效主题列表，如 ['Color', 'Size', 'Color/Size', 'Material']
        """
        return ProductListingVariationBuilder.extract_valid_themes(template_rules)

    def _variation_builder(self) -> ProductListingVariationBuilder:
        return ProductListingVariationBuilder(
            product_data_repo=self.product_data_repo,
            data_mapper=self.data_mapper,
            variation_helper=self.variation_helper,
            variation_theme_service=self.variation_theme_service,
            category_config=self.category_config,
            llm_service=self.llm_service,
        )
    
    def _save_listing_logs(
        self,
        single_skus: List[str],
        variation_logs: List[Dict],
        batch_id: uuid.UUID
    ):
        """保存发品日志"""
        all_logs = build_listing_logs(single_skus, variation_logs, batch_id)
        
        if all_logs:
            self.listing_log_repo.bulk_insert_log(all_logs)
            logger.info(f"  保存了 {len(all_logs)} 条日志")
