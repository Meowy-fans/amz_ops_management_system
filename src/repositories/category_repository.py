# src/repositories/category_repository.py

from sqlalchemy.orm import Session
from sqlalchemy import text
import logging
from typing import List, Tuple, Set, Dict

logger = logging.getLogger(__name__)


class CategoryRepository:
    """
    数据仓库层，专门负责与商品品类相关的查询.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_sku_to_category_mapping(self, meow_skus: List[str]) -> List[Tuple[str, str | None]]:
        """
        对于给定的meow_sku列表，查询它们对应的standard_category_name.
        :param meow_skus: 待查找类目的meow_sku列表.
        :return: 一个元组列表，每个元组是 (meow_sku, standard_category_name or None).
        """
        # 这个查询现在是这个模块的核心职责
        query = text("""
                     SELECT DISTINCT m.meow_sku,
                                     scm.standard_category_name
                     FROM meow_sku_map m
                              JOIN
                          giga_product_sync_records psr ON m.vendor_sku = psr.giga_sku AND m.vendor_source = 'giga'
                              LEFT JOIN
                          supplier_categories_map scm ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                              AND scm.supplier_platform = 'giga'
                     WHERE m.meow_sku = ANY (:meow_sku_list);
                     """)

        try:
            logger.info(f"Executing query to map {len(meow_skus)} SKUs to categories...")
            result = self.db.execute(query, {"meow_sku_list": meow_skus}).fetchall()
            logger.info("SKU to category mapping query successful.")
            return result
        except Exception as e:
            logger.exception(f"Failed to execute SKU to category mapping query: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass
            return []

    def get_existing_category_codes(self, platform: str = 'giga') -> Set[str]:
        """
        获取已存在的品类代码
        
        Args:
            platform: 供应商平台，默认 'giga'
            
        Returns:
            已存在的品类代码集合
        """
        query = text("""
            SELECT supplier_category_code
            FROM supplier_categories_map
            WHERE supplier_platform = :platform
        """)
        
        try:
            result = self.db.execute(query, {"platform": platform}).fetchall()
            return {row[0] for row in result}
        except Exception as e:
            logger.exception(f"Failed to fetch existing category codes: {e}")
            return set()
    
    def get_giga_category_codes(self) -> List[Dict]:
        """
        从 giga_product_sync_records 获取所有不同的品类代码及名称
        
        注意：只查询 Giga 平台的数据，因为数据源是 giga_product_sync_records 表
        
        Returns:
            [
                {
                    'category_code': 'CAB001',
                    'category_name': 'Cabinet Storage'
                },
                ...
            ]
        """
        query = text("""
            SELECT DISTINCT 
                category_code,
                raw_data->>'category' as category_name
            FROM giga_product_sync_records
            WHERE category_code IS NOT NULL
                AND category_code != ''
            ORDER BY category_code
        """)
        
        try:
            result = self.db.execute(query).fetchall()
            
            return [
                {
                    'category_code': row[0],
                    'category_name': row[1] if row[1] else row[0]  # 如果 category_name 为空，使用 code
                }
                for row in result
            ]
        except Exception as e:
            logger.exception(f"Failed to fetch Giga category codes: {e}")
            return []
    
    def batch_insert_category_mappings(self, mappings: List[Dict]) -> int:
        """
        批量插入品类映射
        
        Args:
            mappings: 映射数据列表
                [
                    {
                        'supplier_platform': 'giga',
                        'supplier_category_code': 'CAB001',
                        'supplier_category_name': 'Cabinet Storage',
                        'standard_category_name': ''  # 空字符串表示待维护
                    },
                    ...
                ]
        
        Returns:
            成功插入的记录数
        """
        if not mappings:
            return 0
        
        query = text("""
            INSERT INTO supplier_categories_map (
                supplier_platform,
                supplier_category_code,
                supplier_category_name,
                standard_category_name,
                created_at
            )
            VALUES (
                :supplier_platform,
                :supplier_category_code,
                :supplier_category_name,
                :standard_category_name,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (supplier_platform, supplier_category_code) 
            DO NOTHING
        """)
        
        try:
            result = self.db.execute(query, mappings)
            self.db.commit()
            inserted_count = result.rowcount
            logger.info(f"Successfully inserted {inserted_count} category mappings")
            return inserted_count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to batch insert category mappings: {e}", exc_info=True)
            raise
    
    def get_unmapped_categories_with_product_count(self, platform: str = 'giga') -> List[Dict]:
        """
        获取未完成映射的品类及其对应的商品数量
        
        Args:
            platform: 供应商平台，默认 'giga'
            
        Returns:
            [
                {
                    'category_code': 'CAB001',
                    'category_name': 'Cabinet Storage',
                    'product_count': 150
                },
                ...
            ]
            按商品数量降序排列
        """
        query = text("""
            SELECT 
                scm.supplier_category_code as category_code,
                scm.supplier_category_name as category_name,
                COUNT(psr.giga_sku) as product_count
            FROM supplier_categories_map scm
            LEFT JOIN giga_product_sync_records psr 
                ON LOWER(scm.supplier_category_code) = LOWER(psr.category_code)
            WHERE scm.supplier_platform = :platform
                AND (scm.standard_category_name = '' OR scm.standard_category_name IS NULL)
            GROUP BY scm.supplier_category_code, scm.supplier_category_name
            ORDER BY product_count DESC;
        """)
        
        try:
            result = self.db.execute(query, {"platform": platform}).fetchall()
            
            return [
                {
                    'category_code': row[0],
                    'category_name': row[1] if row[1] else row[0],
                    'product_count': row[2]
                }
                for row in result
            ]
        except Exception as e:
            logger.exception(f"Failed to fetch unmapped categories with product count: {e}")
            return []

    def get_category_sample_products(
        self,
        category_code: str,
        limit: int = 5,
    ) -> List[Dict]:
        """Return representative listing-eligible Giga products for one category."""
        query = text("""
            SELECT
                psr.giga_sku,
                psr.raw_data->>'name' AS product_name,
                COALESCE(
                    NULLIF(psr.raw_data->>'category', ''),
                    scm.supplier_category_name,
                    psr.category_code
                ) AS category_name
            FROM giga_product_sync_records psr
            JOIN giga_product_base_prices pbp
                ON psr.giga_sku = pbp.giga_sku
            LEFT JOIN supplier_categories_map scm
                ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                AND scm.supplier_platform = 'giga'
            WHERE LOWER(psr.category_code) = LOWER(:category_code)
              AND psr.raw_data IS NOT NULL
              AND NULLIF(psr.raw_data->>'name', '') IS NOT NULL
              AND psr.is_oversize IS NOT TRUE
              AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
              AND pbp.sku_available IS TRUE
            ORDER BY LENGTH(psr.raw_data->>'name') DESC, psr.giga_sku
            LIMIT :limit;
        """)
        try:
            result = self.db.execute(
                query,
                {"category_code": category_code, "limit": int(limit)},
            ).fetchall()
            return [
                {
                    "giga_sku": row[0],
                    "name": row[1],
                    "category_name": row[2] if row[2] else category_code,
                }
                for row in result
            ]
        except Exception as e:
            logger.exception(
                "Failed to fetch category sample products for %s: %s",
                category_code,
                e,
            )
            return []
    
    def get_valid_amazon_categories(self) -> Set[str]:
        """
        获取所有有效的亚马逊品类名称（从 amazon_cat_templates 表）
        
        Returns:
            有效品类名称的集合（小写）
        """
        query = text("""
            SELECT DISTINCT LOWER(category) as category
            FROM amazon_cat_templates
            WHERE category IS NOT NULL
                AND category != '';
        """)
        
        try:
            result = self.db.execute(query).fetchall()
            return {row[0] for row in result}
        except Exception as e:
            logger.exception(f"Failed to fetch valid Amazon categories: {e}")
            return set()
    
    def batch_update_category_mappings(self, updates: List[Dict]) -> int:
        """
        批量更新品类映射的 standard_category_name
        
        Args:
            updates: 更新数据列表
                [
                    {
                        'supplier_platform': 'giga',
                        'supplier_category_code': 'CAB001',
                        'standard_category_name': 'cabinet'
                    },
                    ...
                ]
        
        Returns:
            成功更新的记录数
        """
        if not updates:
            return 0
        
        query = text("""
            UPDATE supplier_categories_map
            SET standard_category_name = :standard_category_name
            WHERE supplier_platform = :supplier_platform
                AND supplier_category_code = :supplier_category_code;
        """)
        
        try:
            updated_count = 0
            for update in updates:
                result = self.db.execute(query, update)
                updated_count += result.rowcount
            
            self.db.commit()
            logger.info(f"Successfully updated {updated_count} category mappings")
            return updated_count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to batch update category mappings: {e}", exc_info=True)
            raise

    def update_category_mapping_if_unmapped(
        self,
        supplier_platform: str,
        supplier_category_code: str,
        standard_category_name: str,
    ) -> int:
        """Update one category mapping only when it is still unmapped."""
        query = text("""
            UPDATE supplier_categories_map
            SET standard_category_name = :standard_category_name
            WHERE supplier_platform = :supplier_platform
              AND supplier_category_code = :supplier_category_code
              AND (standard_category_name = '' OR standard_category_name IS NULL);
        """)
        params = {
            "supplier_platform": supplier_platform,
            "supplier_category_code": supplier_category_code,
            "standard_category_name": standard_category_name,
        }
        try:
            result = self.db.execute(query, params)
            self.db.commit()
            return result.rowcount
        except Exception as e:
            self.db.rollback()
            logger.error(
                "Failed to update unmapped category %s/%s: %s",
                supplier_platform,
                supplier_category_code,
                e,
                exc_info=True,
            )
            raise
