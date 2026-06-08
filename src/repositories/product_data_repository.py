"""
Product Data Repository
数据仓库层，负责获取单个SKU的完整产品数据
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class ProductDataRepository:
    """
    产品数据仓库
    
    职责：
    - 为单个SKU获取发品所需的所有数据
    - 关联多个表（SKU映射、产品详情、价格、库存等）
    """
    
    def __init__(self, db: Session):
        """
        初始化Repository
        
        Args:
            db: SQLAlchemy Session实例
        """
        self.db = db
    
    def get_full_product_data(self, meow_sku: str) -> Dict[str, Any]:
        """
        获取单个SKU的完整产品数据
        
        关联表：
        - meow_sku_map: SKU映射
        - ds_api_product_details: LLM生成的产品详情
        - giga_product_sync_records: Giga原始数据（JSONB）
        - supplier_categories_map: 品类映射
        - product_final_prices: 最终售价
        - giga_inventory: 库存数量
        
        Args:
            meow_sku: 内部SKU
            
        Returns:
            包含所有字段的字典：
            {
                'meow_sku': 内部SKU,
                'vendor_sku': 供应商SKU,
                'category_name': 品类名称,
                'product_name': 产品名称,
                'product_description': 产品描述,
                'selling_point_1': 卖点1,
                'selling_point_2': 卖点2,
                'selling_point_3': 卖点3,
                'selling_point_4': 卖点4,
                'selling_point_5': 卖点5,
                'raw_data': 原始数据（JSONB）,
                'final_price': 最终售价,
                'total_quantity': 总库存（仓库+在途）
            }
            
        Example:
            >>> repo.get_full_product_data('meow2511080spTk')
            {
                'meow_sku': 'meow2511080spTk',
                'vendor_sku': 'W2615S00273',
                'category_name': 'CABINET',
                'product_name': 'Modern Bathroom Vanity...',
                'raw_data': {...},
                'final_price': 299.99,
                'total_quantity': 150
            }
        """
        query = text("""
            SELECT 
                m.meow_sku,
                m.vendor_sku,
                scm.standard_category_name AS category_name,
                ds.product_name,
                ds.product_description,
                ds.selling_point_1,
                ds.selling_point_2,
                ds.selling_point_3,
                ds.selling_point_4,
                ds.selling_point_5,
                psr.raw_data,
                pfp.final_price,
                pfp.currency AS price_currency,
                pfp.cost_at_pricing,
                pfp.pricing_formula_version,
                pfp.updated_at AS price_updated_at,
                COALESCE(inv.quantity, 0) AS inventory_quantity,
                COALESCE(inv.buyer_qty, 0) AS buyer_qty,
                COALESCE(inv.seller_qty, 0) AS seller_qty,
                inv.last_updated AS inventory_last_updated,
                COALESCE(inv.quantity, 0) AS total_quantity
            FROM meow_sku_map m
                LEFT JOIN ds_api_product_details ds 
                    ON m.vendor_sku = ds.sku_id
                LEFT JOIN giga_product_sync_records psr 
                    ON m.vendor_sku = psr.giga_sku
                LEFT JOIN supplier_categories_map scm
                    ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                    AND scm.supplier_platform = 'giga'
                LEFT JOIN product_final_prices pfp 
                    ON m.meow_sku = pfp.meow_sku
                LEFT JOIN giga_inventory inv 
                    ON m.vendor_sku = inv.giga_sku
            WHERE m.meow_sku = :meow_sku
            ORDER BY psr.id DESC, ds.id DESC
            LIMIT 1;
        """)
        
        try:
            result = self.db.execute(query, {"meow_sku": meow_sku}).mappings().first()
            
            if result:
                data = dict(result)
                logger.debug(f"成功获取SKU {meow_sku} 的完整数据")
                return data
            else:
                logger.warning(f"未找到SKU {meow_sku} 的数据")
                return {}
                
        except Exception as e:
            logger.error(f"❌ 获取SKU {meow_sku} 数据时失败: {e}", exc_info=True)
            raise
