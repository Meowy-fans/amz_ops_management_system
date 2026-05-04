"""Giga商品同步服务"""
import logging
import time
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from infrastructure.giga.api_client import GigaAPIClient, GigaAPIException
from src.repositories.giga_product_sync_repository import GigaProductSyncRepository
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)

class GigaSyncService:
    """Giga商品同步服务"""
    
    def __init__(self, db: Session, reporter: ProgressReporter | None = None):
        self.db = db
        self.api_client = GigaAPIClient()
        self.repository = GigaProductSyncRepository(db)
        self.reporter = reporter or ProgressReporter()
    
    def get_full_sku_list(
        self,
        limit_per_page: int = 100,
        sort: int = 4
    ) -> List[str]:
        """获取完整SKU列表（分页）"""
        logger.info("开始获取Giga全量SKU列表...")
        
        all_skus = []
        page = 1
        total_count = 0
        
        try:
            while True:
                params = {
                    'limit': limit_per_page,
                    'page': page,
                    'sort': sort
                }
                
                logger.info(f"正在获取第{page}页...")
                
                try:
                    response = self.api_client.execute(
                        endpoint_name='product_list',
                        payload=params,
                        method='GET'
                    )
                except GigaAPIException as e:
                    logger.error(f"API请求失败: {e}")
                    break
                
                body = response.get('body', {})
                page_meta = body.get('pageMeta', {})
                
                if page == 1:
                    total_count = page_meta.get('total', 0)
                    logger.info(f"API报告总SKU数: {total_count}")
                
                data = body.get('data', [])
                skus = [item.get('sku') for item in data if item.get('sku')]
                all_skus.extend(skus)
                
                logger.info(f"第{page}页获取{len(skus)}个SKU，累计{len(all_skus)}个")
                
                has_next = bool(page_meta.get('next'))
                if not has_next or len(data) < limit_per_page:
                    break
                
                headers = response.get('headers', {})
                rate_limit = headers.get('X-RateLimit-Remaining', '10')
                if int(rate_limit) < 3:
                    time.sleep(1.5)
                else:
                    time.sleep(0.5)
                
                page += 1
            
            logger.info(f"SKU列表获取完成，共{len(all_skus)}个")
            
            if total_count > 0 and len(all_skus) != total_count:
                logger.warning(f"数据不一致！获取{len(all_skus)}条，API报告{total_count}条")
            
            return all_skus
            
        except Exception as e:
            logger.exception(f"获取SKU列表失败: {e}")
            return all_skus
    
    def sync_product_details(
        self,
        sku_list: List[str],
        batch_size: int = 50
    ) -> Dict[str, int]:
        """
        同步商品详情
        
        ⚠️ 修复：参数名改为 skus（不是skuList）
        """
        total = len(sku_list)
        success = 0
        failed = 0
        
        logger.info(f"开始同步{total}个商品详情...")
        
        for i in range(0, total, batch_size):
            batch = sku_list[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            logger.info(f"处理第{batch_num}批，共{len(batch)}个SKU")
            
            try:
                # ✅ 修复：参数名改为 skus
                response = self.api_client.execute(
                    endpoint_name='product_details',
                    payload={'skus': batch},  # 改为 skus
                    method='POST'
                )
                
                body = response.get('body', {})
                products = body.get('data', [])
                
                if not products:
                    logger.warning(f"第{batch_num}批返回空数据")
                    failed += len(batch)
                    continue
                
                # 保存到数据库
                saved = self.repository.batch_upsert_products(products)
                success += saved
                failed += (len(batch) - saved)
                
                logger.info(f"第{batch_num}批: 成功保存{saved}个")
                
                # 提交事务
                self.db.commit()
                
                # 限流
                time.sleep(0.3)
                
            except GigaAPIException as e:
                logger.error(f"第{batch_num}批API错误: {e}")
                failed += len(batch)
                self.db.rollback()
                
            except Exception as e:
                logger.exception(f"第{batch_num}批处理失败: {e}")
                failed += len(batch)
                self.db.rollback()
        
        logger.info(f"同步完成: 总计{total}，成功{success}，失败{failed}")
        
        return {
            'total': total,
            'success': success,
            'failed': failed
        }
    
    def sync_full_products(self) -> Dict[str, Any]:
        """完整同步流程"""
        logger.info("🚀 开始完整同步流程...")
        
        self.reporter.emit("➡️ 步骤1/2: 获取SKU列表...")
        sku_list = self.get_full_sku_list()
        
        if not sku_list:
            self.reporter.emit("✅ 未获取到SKU，流程结束")
            return {'total': 0, 'success': 0, 'failed': 0}
        
        self.reporter.emit(f"✔️ 成功获取{len(sku_list)}个SKU")
        
        self.reporter.emit("➡️ 步骤2/2: 同步商品详情...")
        result = self.sync_product_details(sku_list)
        
        stats = self.repository.get_statistics()
        
        self.reporter.emit("\n" + "="*60)
        self.reporter.emit("✅ 同步完成！")
        self.reporter.emit("="*60)
        self.reporter.emit(f"本次同步: 总计{result['total']}，成功{result['success']}，失败{result['failed']}")
        self.reporter.emit(f"数据库统计: 总记录{stats['total']}，超大件{stats['oversize']}")
        self.reporter.emit("="*60 + "\n")
        
        return result
