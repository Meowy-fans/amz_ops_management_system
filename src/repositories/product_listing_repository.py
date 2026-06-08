"""
Product Listing Repository
数据仓库层，负责商品发品相关的复杂查询
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class ProductListingRepository:
    """
    商品发品数据仓库
    
    职责：
    - 筛选待发布的SKU（基于多表关联的复杂业务规则）
    - 获取SKU的变体关联数据
    - 获取SKU到品类的映射关系
    """
    
    def __init__(self, db: Session):
        """
        初始化Repository
        
        Args:
            db: SQLAlchemy Session实例
        """
        self.db = db
    
    def get_pending_listing_skus(self) -> List[str]:
        """
        筛选所有具备本地发布资格的meow_sku

        业务规则：
        1. 非超大件商品（is_oversize != TRUE）
        2. 普通卖家类型（sellerType = 'GENERAL'）
        3. 有可用价格（sku_available = TRUE）

        是否已存在于 Amazon 不再依赖 amz_all_listing_report，
        真实 API 发品前由 Listings Items API 实时查重。
        
        Returns:
            具备本地发布资格的meow_sku列表
            
        Raises:
            Exception: 数据库查询失败时抛出
        """
        query = text("""
            SELECT DISTINCT m.meow_sku
            FROM meow_sku_map m
                JOIN giga_product_sync_records psr 
                    ON m.vendor_sku = psr.giga_sku 
                    AND m.vendor_source = 'giga'
                JOIN giga_product_base_prices pbp 
                    ON m.vendor_sku = pbp.giga_sku
            WHERE psr.is_oversize IS NOT TRUE
              AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
              AND pbp.sku_available IS TRUE
            ORDER BY m.meow_sku;
        """)
        
        try:
            logger.info("执行待发布SKU筛选查询...")
            result = self.db.execute(query).scalars().all()
            logger.info(f"✅ 筛选完成，找到 {len(result)} 个待发布SKU")
            return list(result)
            
        except Exception as e:
            logger.error(f"❌ 筛选待发布SKU时失败: {e}", exc_info=True)
            raise
    
    def get_variation_data(self, meow_skus: List[str]) -> List[Tuple[str, str, List[str]]]:
        """
        获取SKU的变体关联数据
        
        用于判断哪些SKU属于同一变体家族。
        使用窗口函数确保每个vendor_sku只返回最新的记录。
        
        Args:
            meow_skus: 待查询的meow_sku列表
            
        Returns:
            元组列表，每个元组为 (meow_sku, vendor_sku, associateProductList)
            - meow_sku: 内部SKU
            - vendor_sku: 供应商SKU（Giga SKU）
            - associateProductList: 关联的产品SKU列表（用于构建变体图）
            
        Example:
            >>> repo.get_variation_data(['MEOW-001', 'MEOW-002'])
            [
                ('MEOW-001', 'GIGA-A', ['GIGA-B', 'GIGA-C']),
                ('MEOW-002', 'GIGA-B', ['GIGA-A', 'GIGA-C'])
            ]
        """
        if not meow_skus:
            logger.warning("get_variation_data 接收到空的SKU列表")
            return []
        
        query = text("""
            WITH latest_records AS (
                SELECT 
                    giga_sku,
                    raw_data,
                    ROW_NUMBER() OVER(PARTITION BY giga_sku ORDER BY id DESC) as rn
                FROM giga_product_sync_records
            )
            SELECT 
                m.meow_sku,
                m.vendor_sku,
                COALESCE(lr.raw_data -> 'associateProductList', '[]'::jsonb) AS associate_list
            FROM meow_sku_map m
                JOIN latest_records lr 
                    ON m.vendor_sku = lr.giga_sku
            WHERE lr.rn = 1
              AND m.meow_sku = ANY(:meow_sku_list);
        """)
        
        try:
            logger.info(f"获取 {len(meow_skus)} 个SKU的变体数据...")
            results = self.db.execute(query, {"meow_sku_list": meow_skus}).fetchall()
            
            # 清理结果，确保 associate_list 是列表类型
            cleaned_results = []
            for meow_sku, vendor_sku, assoc_list in results:
                # assoc_list 应该已经是Python列表（JSONB自动解析）
                if assoc_list is None:
                    cleaned_results.append((meow_sku, vendor_sku, []))
                elif isinstance(assoc_list, list):
                    cleaned_results.append((meow_sku, vendor_sku, assoc_list))
                else:
                    # 容错处理
                    logger.warning(f"SKU {meow_sku} 的 associateProductList 格式异常: {type(assoc_list)}")
                    cleaned_results.append((meow_sku, vendor_sku, []))
            
            logger.info(f"✅ 成功获取 {len(cleaned_results)} 个SKU的变体数据")
            return cleaned_results
            
        except Exception as e:
            logger.error(f"❌ 获取变体数据时失败: {e}", exc_info=True)
            raise

    def get_meow_skus_by_vendor_skus(self, vendor_skus: List[str]) -> Dict[str, str]:
        """Return Giga vendor SKU to meow SKU mapping for existing family lookup."""
        if not vendor_skus:
            logger.warning("get_meow_skus_by_vendor_skus 接收到空的SKU列表")
            return {}

        query = text("""
            SELECT vendor_sku, meow_sku
            FROM meow_sku_map
            WHERE vendor_source = 'giga'
              AND vendor_sku = ANY(:vendor_sku_list);
        """)

        try:
            logger.info("映射 %d 个 Giga SKU 到 meow_sku...", len(vendor_skus))
            results = self.db.execute(
                query,
                {"vendor_sku_list": vendor_skus},
            ).fetchall()
            return {vendor_sku: meow_sku for vendor_sku, meow_sku in results}
        except Exception as e:
            logger.error("❌ Giga SKU 映射 meow_sku 失败: %s", e, exc_info=True)
            raise
    
    def get_sku_to_category_mapping(self, meow_skus: List[str]) -> List[Tuple[str, str]]:
        """
        获取SKU到标准品类的映射关系
        
        通过以下路径映射：
        meow_sku → vendor_sku → category_code → standard_category_name
        
        Args:
            meow_skus: 待查询的meow_sku列表
            
        Returns:
            元组列表，每个元组为 (meow_sku, standard_category_name)
            如果某个SKU未映射到品类，standard_category_name为None
            
        Example:
            >>> repo.get_sku_to_category_mapping(['MEOW-001', 'MEOW-002'])
            [
                ('MEOW-001', 'CABINET'),
                ('MEOW-002', 'HOME_MIRROR'),
                ('MEOW-003', None)  # 未映射到品类
            ]
        """
        if not meow_skus:
            logger.warning("get_sku_to_category_mapping 接收到空的SKU列表")
            return []
        
        query = text("""
            SELECT DISTINCT 
                m.meow_sku,
                scm.standard_category_name
            FROM meow_sku_map m
                JOIN giga_product_sync_records psr 
                    ON m.vendor_sku = psr.giga_sku 
                    AND m.vendor_source = 'giga'
                LEFT JOIN supplier_categories_map scm 
                    ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                    AND scm.supplier_platform = 'giga'
            WHERE m.meow_sku = ANY(:meow_sku_list)
            ORDER BY m.meow_sku;
        """)
        
        try:
            logger.info(f"映射 {len(meow_skus)} 个SKU到品类...")
            results = self.db.execute(query, {"meow_sku_list": meow_skus}).fetchall()
            logger.info(f"✅ 成功映射 {len(results)} 个SKU")
            return list(results)
            
        except Exception as e:
            logger.error(f"❌ SKU品类映射时失败: {e}", exc_info=True)
            raise
