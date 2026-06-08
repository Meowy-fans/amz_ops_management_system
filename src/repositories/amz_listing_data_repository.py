"""
Amazon Listing Data Repository
亚马逊上架商品数据仓库

负责为库存价格更新流程，从数据库中提取所需的数据
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class ListingDataRepository:
    """
    负责为库存价格更新流程，从数据库中提取所需的数据。
    """
    
    def __init__(self, db: Session):
        """
        初始化仓库
        
        Args:
            db: SQLAlchemy Session 对象
        """
        self.db = db

    def get_skus_for_update(self) -> List[Dict[str, str]]:
        """
        获取需要更新的SKU列表。
        
        逻辑：
        - 从 amazon_listing_items_cache 获取 amazon_sku
        - 通过 meow_sku_map 关联到 giga_sku (vendor_sku)
        - Amazon cache 由 Listings Items API searchListingsItems/getListingsItem 刷新
        
        Returns:
            SKU映射列表，每个元素包含 amazon_sku 和 giga_sku
        """
        logger.info("正在从数据库获取 SKU 映射关系...")
        
        query = text("""
            SELECT
                cache.sku AS amazon_sku,
                msm.vendor_sku AS giga_sku,
                cache.product_type AS product_type
            FROM
                amazon_listing_items_cache cache
            JOIN
                meow_sku_map msm ON cache.sku = msm.meow_sku
            WHERE
                msm.vendor_sku IS NOT NULL
            ORDER BY cache.sku;
        """)
        
        try:
            result = self.db.execute(query).mappings().all()
            sku_map = [dict(row) for row in result]
            logger.info(f"成功获取 {len(sku_map)} 条需要处理的 SKU 映射。")
            return sku_map
        except Exception as e:
            logger.error(f"获取SKU映射失败: {e}", exc_info=True)
            return []

    def get_latest_data(
        self, 
        amazon_skus: List[str], 
        giga_skus: List[str]
    ) -> Tuple[Dict[str, float], Dict[str, int]]:
        """
        根据给定的SKU列表，批量获取最新的价格和库存。
        
        Args:
            amazon_skus: Amazon SKU列表（用于查询价格）
            giga_skus: Giga SKU列表（用于查询库存）
            
        Returns:
            元组 (价格字典, 库存字典)
            - 价格字典: {amazon_sku: final_price}
            - 库存字典: {giga_sku: quantity}
        """
        price_map = {}
        quantity_map = {}

        # 批量获取价格
        if amazon_skus:
            logger.info(f"正在批量获取 {len(amazon_skus)} 个SKU的价格...")
            price_query = text("""
                SELECT meow_sku, final_price 
                FROM product_final_prices
                WHERE meow_sku = ANY(:skus)
            """)
            try:
                price_result = self.db.execute(
                    price_query, 
                    {"skus": amazon_skus}
                ).all()
                price_map = {row[0]: row[1] for row in price_result}
                logger.info(f"成功获取 {len(price_map)} 条价格数据。")
            except Exception as e:
                logger.error(f"批量获取价格失败: {e}", exc_info=True)

        # 批量获取库存
        if giga_skus:
            logger.info(f"正在批量获取 {len(giga_skus)} 个SKU的库存...")
            quantity_query = text("""
                SELECT giga_sku, quantity 
                FROM giga_inventory
                WHERE giga_sku = ANY(:skus)
            """)
            try:
                quantity_result = self.db.execute(
                    quantity_query, 
                    {"skus": giga_skus}
                ).all()
                quantity_map = {row[0]: row[1] for row in quantity_result}
                logger.info(f"成功获取 {len(quantity_map)} 条库存数据。")
            except Exception as e:
                logger.error(f"批量获取库存失败: {e}", exc_info=True)

        return price_map, quantity_map
