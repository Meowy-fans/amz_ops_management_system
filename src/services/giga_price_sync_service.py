"""Giga商品价格同步服务（批量优化版）"""
import logging
import time
from typing import List, Dict
from sqlalchemy.orm import Session
from infrastructure.giga.api_client import GigaAPIClient, GigaAPIException
from src.repositories.giga_product_price_repository import GigaProductPriceRepository
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)

class GigaPriceSyncService:
    """Giga商品价格同步服务"""
    
    def __init__(
        self,
        db: Session,
        batch_size: int = 200,
        max_retries: int = 3,
        api_rate_limit: int = 9,
        wait_time: int = 10,
        reporter: ProgressReporter | None = None
    ):
        self.db = db
        self.repository = GigaProductPriceRepository(db)
        self.api_client = GigaAPIClient()
        self.reporter = reporter or ProgressReporter()
        
        # 配置参数
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.api_rate_limit = api_rate_limit
        self.wait_time = wait_time
    
    def fetch_batch_prices(self, skus: List[str]) -> List[Dict]:
        """获取批次商品价格（带重试）"""
        logger.info(f"⏳ 正在请求 {len(skus)} 个SKU的价格...")
        self.reporter.emit(f"   ⏳ 正在请求API（{len(skus)}个SKU）...")
        
        request_start = time.time()
        
        for attempt in range(self.max_retries):
            try:
                payload = {"skus": skus}
                response = self.api_client.execute(
                    "product_price",
                    payload,
                    method="POST"
                )
                
                elapsed = time.time() - request_start
                
                body = response.get('body', {})
                if not body.get('success'):
                    error_msg = body.get('error', '未知API错误')
                    raise GigaAPIException(f"API返回错误: {error_msg}")
                
                data = body.get('data', [])
                logger.info(f"✅ API响应成功，耗时 {elapsed:.2f}秒，获取 {len(data)} 条数据")
                self.reporter.emit(f"   ✅ API响应成功（耗时 {elapsed:.1f}秒，返回 {len(data)} 条）")
                
                return data
                
            except Exception as e:
                elapsed = time.time() - request_start
                
                if attempt < self.max_retries - 1:
                    delay = 2 ** attempt
                    logger.warning(f"API调用失败（耗时{elapsed:.1f}秒），{delay}秒后重试 ({attempt+1}/{self.max_retries}): {e}")
                    self.reporter.emit(f"   ⚠️ 重试中... ({attempt+1}/{self.max_retries})")
                    time.sleep(delay)
                else:
                    logger.error(f"API调用失败，已达最大重试次数（总耗时{elapsed:.1f}秒）: {e}")
                    self.reporter.emit(f"   ❌ API请求失败")
                    raise
    
    def sync_all_prices(self) -> Dict[str, int]:
        """同步全量商品价格"""
        logger.info("🚀 开始同步全量商品价格...")
        start_time = time.time()
        
        # 1. 获取所有SKU
        all_skus = self.repository.get_all_skus()
        total_skus = len(all_skus)
        
        if not total_skus:
            logger.info("没有需要更新的SKU")
            self.reporter.emit("✅ 没有需要更新的SKU")
            return {'total': 0, 'success': 0, 'failed': 0}
        
        logger.info(f"共获取 {total_skus} 个商品SKU")
        self.reporter.emit(f"\n📊 待同步SKU总数: {total_skus}")
        self.reporter.emit(f"📦 批次大小: {self.batch_size}\n")
        
        # 2. 分批处理
        batches = [
            all_skus[i:i + self.batch_size]
            for i in range(0, total_skus, self.batch_size)
        ]
        total_batches = len(batches)
        
        total_success = 0
        total_failure = 0
        
        for i, batch in enumerate(batches):
            batch_num = i + 1
            batch_start = time.time()
            success = 0
            failure = 0
            
            logger.info(f"处理批次 {batch_num}/{total_batches} ({len(batch)}个SKU)")
            self.reporter.emit(f"🔄 处理批次 {batch_num}/{total_batches}...")
            
            # API限流控制
            if i > 0 and i % self.api_rate_limit == 0:
                logger.info(f"等待{self.wait_time}秒以满足API限流要求...")
                self.reporter.emit(f"   ⏸️  限流等待{self.wait_time}秒...")
                time.sleep(self.wait_time)
            
            try:
                # 获取价格
                prices = self.fetch_batch_prices(batch)
                
                # 批量保存（一次性提交）
                self.reporter.emit(f"   💾 保存数据...")
                save_start = time.time()
                
                success, failure = self.repository.batch_upsert_prices(prices)
                self.db.commit()
                
                save_elapsed = time.time() - save_start
                logger.info(f"数据保存完成，耗时 {save_elapsed:.2f}秒")
                
                total_success += success
                total_failure += failure
                
                batch_elapsed = time.time() - batch_start
                logger.info(f"批次完成，总耗时 {batch_elapsed:.1f}秒")
                
            except Exception as e:
                self.db.rollback()
                total_failure += len(batch)
                logger.error(f"处理批次失败: {e}")
                self.reporter.emit(f"   ❌ 批次失败: {e}")
            
            # 进度报告
            processed = min((i + 1) * self.batch_size, total_skus)
            progress = processed / total_skus * 100
            
            logger.info(f"进度: {progress:.1f}% | 成功: {total_success} | 失败: {total_failure}")
            self.reporter.emit(f"   ✔️ 成功: {success}/{len(batch)}")
            self.reporter.emit(f"   📈 总进度: {processed}/{total_skus} ({progress:.1f}%)\n")
        
        # 3. 最终统计
        elapsed = time.time() - start_time
        
        self.reporter.emit("\n" + "="*60)
        self.reporter.emit("✅ 价格同步完成！")
        self.reporter.emit("="*60)
        self.reporter.emit(f"总计: {total_skus}")
        self.reporter.emit(f"成功: {total_success}")
        self.reporter.emit(f"失败: {total_failure}")
        self.reporter.emit(f"耗时: {elapsed:.2f}秒 ({elapsed/60:.2f}分钟)")
        self.reporter.emit("="*60 + "\n")
        
        logger.info(f"同步完成! 总计: {total_skus} | 成功: {total_success} | 失败: {total_failure}")
        logger.info(f"耗时: {elapsed:.2f}秒")
        
        return {
            'total': total_skus,
            'success': total_success,
            'failed': total_failure
        }
