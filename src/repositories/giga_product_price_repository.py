"""Giga商品价格Repository（过滤无效价格版）"""
import logging
import csv
from io import StringIO
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.repositories.giga_price_transform import parse_datetime, prepare_price_rows

logger = logging.getLogger(__name__)

class GigaProductPriceRepository:
    """Giga商品价格数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_all_skus(self) -> List[str]:
        """获取所有Giga商品SKU"""
        try:
            query = text("""
                SELECT DISTINCT giga_sku 
                FROM giga_product_sync_records 
                WHERE giga_sku IS NOT NULL
                ORDER BY giga_sku
            """)
            
            result = self.db.execute(query).fetchall()
            skus = [row[0] for row in result]
            
            logger.info(f"获取到{len(skus)}个SKU")
            return skus
            
        except Exception as e:
            logger.error(f"获取SKU列表失败: {e}")
            return []
    
    def batch_upsert_prices(self, prices: List[Dict]) -> Tuple[int, int]:
        """
        批量插入/更新价格（过滤无效价格版）
        
        Returns:
            (成功数量, 失败数量)
        """
        if not prices:
            return 0, 0
        
        base_price_data, tier_price_data, success_count, failed_skus = (
            prepare_price_rows(prices)
        )
        
        # 4. 批量插入基础价格（使用临时表 + COPY）
        if base_price_data:
            try:
                self._bulk_upsert_base_prices(base_price_data)
                logger.info(f"批量插入基础价格: {len(base_price_data)}条")
            except Exception as e:
                logger.error(f"批量插入基础价格失败: {e}")
                return 0, success_count + len(failed_skus)
        
        # 5. 批量插入梯度价格（使用COPY）
        if tier_price_data:
            try:
                self._bulk_upsert_tier_prices(tier_price_data)
                logger.info(f"批量插入梯度价格: {len(tier_price_data)}条")
            except Exception as e:
                logger.error(f"批量插入梯度价格失败: {e}")
                # 梯度失败不影响基础价格
        
        return success_count, len(failed_skus)
    
    def _bulk_upsert_base_prices(self, data: List[Dict]):
        """使用临时表 + COPY批量UPSERT基础价格"""
        connection = self.db.connection().connection
        
        with connection.cursor() as cursor:
            # 1. 创建临时表
            cursor.execute("""
                CREATE TEMP TABLE tmp_base_prices (
                    giga_sku VARCHAR(100),
                    currency CHAR(3),
                    base_price NUMERIC(10,2),
                    shipping_fee NUMERIC(10,2),
                    shipping_fee_min NUMERIC(10,2),
                    shipping_fee_max NUMERIC(10,2),
                    exclusive_price NUMERIC(10,2),
                    discounted_price NUMERIC(10,2),
                    promotion_start TIMESTAMP WITH TIME ZONE,
                    promotion_end TIMESTAMP WITH TIME ZONE,
                    map_price NUMERIC(10,2),
                    future_map_price NUMERIC(10,2),
                    effect_map_time TIMESTAMP WITH TIME ZONE,
                    sku_available BOOLEAN,
                    seller_info JSONB,
                    full_response JSONB
                ) ON COMMIT DROP
            """)
            
            # 2. 构建CSV数据
            csv_data = StringIO()
            writer = csv.writer(csv_data)
            
            for item in data:
                writer.writerow([
                    item['giga_sku'],
                    item['currency'],
                    item['base_price'],
                    item['shipping_fee'],
                    item['shipping_fee_min'],
                    item['shipping_fee_max'],
                    item['exclusive_price'],
                    item['discounted_price'],
                    item['promotion_start'],
                    item['promotion_end'],
                    item['map_price'],
                    item['future_map_price'],
                    item['effect_map_time'],
                    item['sku_available'],
                    item['seller_info'],
                    item['full_response']
                ])
            
            csv_data.seek(0)
            
            # 3. COPY导入临时表
            cursor.copy_expert(
                sql="COPY tmp_base_prices FROM STDIN WITH CSV",
                file=csv_data
            )
            
            # 4. UPSERT到正式表
            cursor.execute("""
                INSERT INTO giga_product_base_prices (
                    giga_sku, currency, base_price, shipping_fee,
                    shipping_fee_min, shipping_fee_max, exclusive_price,
                    discounted_price, promotion_start, promotion_end,
                    map_price, future_map_price, effect_map_time,
                    sku_available, seller_info, full_response, updated_at
                )
                SELECT 
                    giga_sku, currency, base_price, shipping_fee,
                    shipping_fee_min, shipping_fee_max, exclusive_price,
                    discounted_price, promotion_start, promotion_end,
                    map_price, future_map_price, effect_map_time,
                    sku_available, seller_info, full_response, CURRENT_TIMESTAMP
                FROM tmp_base_prices
                ON CONFLICT (giga_sku) DO UPDATE SET
                    currency = EXCLUDED.currency,
                    base_price = EXCLUDED.base_price,
                    shipping_fee = EXCLUDED.shipping_fee,
                    shipping_fee_min = EXCLUDED.shipping_fee_min,
                    shipping_fee_max = EXCLUDED.shipping_fee_max,
                    exclusive_price = EXCLUDED.exclusive_price,
                    discounted_price = EXCLUDED.discounted_price,
                    promotion_start = EXCLUDED.promotion_start,
                    promotion_end = EXCLUDED.promotion_end,
                    map_price = EXCLUDED.map_price,
                    future_map_price = EXCLUDED.future_map_price,
                    effect_map_time = EXCLUDED.effect_map_time,
                    sku_available = EXCLUDED.sku_available,
                    seller_info = EXCLUDED.seller_info,
                    full_response = EXCLUDED.full_response,
                    updated_at = CURRENT_TIMESTAMP
            """)
    
    def _bulk_upsert_tier_prices(self, data: List[Dict]):
        """使用临时表 + COPY批量插入梯度价格"""
        if not data:
            return
        
        connection = self.db.connection().connection
        
        with connection.cursor() as cursor:
            # 1. 删除旧梯度（本批次涉及的SKU）
            skus = list(set(item['giga_sku'] for item in data))
            cursor.execute(
                """
                DELETE FROM giga_price_tiers 
                WHERE base_price_id IN (
                    SELECT id FROM giga_product_base_prices 
                    WHERE giga_sku = ANY(%s)
                )
                """,
                (skus,)
            )
            
            # 2. 创建临时表
            cursor.execute("""
                CREATE TEMP TABLE tmp_tier_prices (
                    giga_sku VARCHAR(100),
                    tier_type VARCHAR(10),
                    min_quantity INTEGER,
                    max_quantity INTEGER,
                    price NUMERIC(10,2),
                    discounted_price NUMERIC(10,2),
                    effective_date TIMESTAMP WITH TIME ZONE
                ) ON COMMIT DROP
            """)
            
            # 3. 构建CSV数据
            csv_data = StringIO()
            writer = csv.writer(csv_data)
            
            for item in data:
                writer.writerow([
                    item['giga_sku'],
                    item['tier_type'],
                    item['min_quantity'],
                    item['max_quantity'],
                    item['price'],
                    item['discounted_price'],
                    item['effective_date']
                ])
            
            csv_data.seek(0)
            
            # 4. COPY导入临时表
            cursor.copy_expert(
                sql="COPY tmp_tier_prices FROM STDIN WITH CSV",
                file=csv_data
            )
            
            # 5. JOIN插入正式表（将SKU转为ID）
            cursor.execute("""
                INSERT INTO giga_price_tiers (
                    base_price_id, tier_type, min_quantity,
                    max_quantity, price, discounted_price, effective_date
                )
                SELECT 
                    bp.id,
                    tmp.tier_type,
                    tmp.min_quantity,
                    tmp.max_quantity,
                    tmp.price,
                    tmp.discounted_price,
                    tmp.effective_date
                FROM tmp_tier_prices tmp
                INNER JOIN giga_product_base_prices bp 
                    ON bp.giga_sku = tmp.giga_sku
            """)
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """解析时间字符串"""
        if not dt_str:
            return None
        try:
            return parse_datetime(dt_str)
        except ValueError:
            return None
    
    def get_statistics(self) -> Dict[str, int]:
        """获取价格统计"""
        try:
            result = self.db.execute(
                text("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE sku_available = true) as available,
                        COUNT(DISTINCT currency) as currencies
                    FROM giga_product_base_prices
                """)
            ).fetchone()
            
            tier_count = self.db.execute(
                text("SELECT COUNT(*) FROM giga_price_tiers")
            ).scalar()
            
            return {
                'total_prices': result[0] or 0,
                'available_skus': result[1] or 0,
                'currencies': result[2] or 0,
                'total_tiers': tier_count or 0
            }
        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            return {'total_prices': 0, 'available_skus': 0, 'currencies': 0, 'total_tiers': 0}
