"""LLM生成的商品详情Repository"""
import logging
import json
from typing import List, Optional, Dict, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class LLMProductDetailRepository:
    """LLM生成的商品详情数据仓库（通用于所有LLM提供商）"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_unprocessed_skus(self) -> List[str]:
        """获取未处理的SKU列表"""
        try:
            query = text("""
                SELECT DISTINCT giga_sku
                FROM giga_product_sync_records
                WHERE raw_data IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM ds_api_product_details 
                      WHERE sku_id = giga_sku
                  )
                ORDER BY giga_sku ASC
            """)
            
            result = self.db.execute(query).fetchall()
            skus = [row[0] for row in result]
            
            logger.info(f"获取到{len(skus)}个待处理SKU")
            return skus
            
        except Exception as e:
            logger.error(f"获取未处理SKU失败: {e}")
            return []
    
    def get_product_raw_data(self, sku: str) -> Optional[dict]:
        """获取商品原始数据"""
        try:
            query = text("""
                SELECT raw_data
                FROM giga_product_sync_records
                WHERE giga_sku = :sku
                LIMIT 1
            """)
            
            result = self.db.execute(query, {"sku": sku}).fetchone()
            
            if not result or not result[0]:
                logger.warning(f"SKU {sku} 无原始数据")
                return None
            
            return result[0] if isinstance(result[0], dict) else json.loads(result[0])
            
        except Exception as e:
            logger.error(f"获取SKU {sku} 原始数据失败: {e}")
            return None

    def get_product_type_for_sku(self, sku: str) -> Optional[str]:
        """Resolve the Amazon standard category/product type for a Giga SKU."""
        try:
            query = text("""
                SELECT scm.standard_category_name
                FROM giga_product_sync_records psr
                    LEFT JOIN supplier_categories_map scm
                        ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                        AND scm.supplier_platform = 'giga'
                WHERE psr.giga_sku = :sku
                ORDER BY psr.id DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"sku": sku}).fetchone()
            if not result or not result[0]:
                return None
            return str(result[0]).upper()

        except Exception as e:
            logger.error(f"获取SKU {sku} 标准品类失败: {e}")
            return None
    
    def batch_save_details(self, details: List[Tuple]) -> int:
        """批量保存商品详情"""
        if not details:
            return 0
        
        try:
            stmt = text("""
                INSERT INTO ds_api_product_details (
                    sku_id, product_name,
                    selling_point_1, selling_point_2, selling_point_3,
                    selling_point_4, selling_point_5,
                    product_description, calling_agent, raw_json
                )
                VALUES (
                    :sku_id, :product_name,
                    :sp1, :sp2, :sp3, :sp4, :sp5,
                    :product_desc, :calling_agent, CAST(:raw_json AS jsonb)
                )
            """)
            
            params_list = [
                {
                    "sku_id": d[0],
                    "product_name": d[1],
                    "sp1": d[2],
                    "sp2": d[3],
                    "sp3": d[4],
                    "sp4": d[5],
                    "sp5": d[6],
                    "product_desc": d[7],
                    "calling_agent": d[8],
                    "raw_json": d[9]
                }
                for d in details if d
            ]
            
            if not params_list:
                return 0
            
            self.db.execute(stmt, params_list)
            self.db.commit()
            
            logger.info(f"批量保存成功: {len(params_list)}条")
            return len(params_list)
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"批量保存失败: {e}")
            return 0
    
    def get_statistics(self) -> Dict[str, int]:
        """获取统计信息"""
        try:
            result = self.db.execute(
                text("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(DISTINCT sku_id) as unique_skus
                    FROM ds_api_product_details
                """)
            ).fetchone()
            
            return {
                'total': result[0] or 0,
                'unique_skus': result[1] or 0
            }
        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            return {'total': 0, 'unique_skus': 0}
