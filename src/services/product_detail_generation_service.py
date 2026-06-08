"""商品详情生成服务"""
import json
import logging
import time
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session

from infrastructure.llm import get_llm_service
from infrastructure.db_pool import SessionLocal
from src.repositories.llm_product_detail_repository import LLMProductDetailRepository
from src.services.product_content_generator import ProductContentGenerator
from src.services.product_normalizer import GigaProductNormalizer
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)

class ProductDetailGenerationService:
    """商品详情生成服务"""
    
    def __init__(
        self, 
        db: Session,
        batch_size: int = 50,
        max_retries: int = 3,
        thread_count: int = 4,
        max_input_length: int = 10000,  # ✅ 默认10000字符
        reporter: ProgressReporter | None = None
    ):
        self.db = db
        self.repository = LLMProductDetailRepository(db)
        self.llm_service = get_llm_service()
        self.content_generator = ProductContentGenerator(llm_service=self.llm_service)
        self.normalizer = GigaProductNormalizer()
        self.reporter = reporter or ProgressReporter()
        
        # 配置参数
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.thread_count = thread_count
        self.max_input_length = max_input_length
        
        # 统计
        self.processed_count = 0
        self.failed_count = 0
    
    def process_single_sku(self, sku: str) -> Optional[Tuple]:
        """
        处理单个SKU
        
        Returns:
            成功返回详情元组，失败返回None
        """
        # 使用独立的数据库会话（线程安全）
        with SessionLocal() as thread_db:
            thread_repo = LLMProductDetailRepository(thread_db)
            
            try:
                # 1. 获取原始数据
                raw_data = thread_repo.get_product_raw_data(sku)
                if not raw_data:
                    logger.warning(f"SKU {sku} 无原始数据")
                    return None

                product_type = thread_repo.get_product_type_for_sku(sku) or "UNKNOWN"
                standard_product = self.normalizer.normalize(
                    raw_data=raw_data,
                    vendor_sku=sku,
                )

                # 2. 调用 v2 品类感知内容生成器（带重试）
                for attempt in range(self.max_retries):
                    try:
                        content = self.content_generator.generate(
                            standard_product,
                            product_type=product_type,
                        )

                        if not content.title or not content.description:
                            warning_text = "; ".join(content.validation_warnings)
                            raise ValueError(
                                warning_text or "v2 content generator returned empty content"
                            )

                        return self._build_detail_tuple(sku, product_type, content)
                        
                    except Exception as e:
                        if attempt < self.max_retries - 1:
                            logger.warning(f"SKU {sku} 尝试{attempt+1}失败: {e}")
                            time.sleep(2 ** attempt)  # 指数退避
                        else:
                            logger.error(f"SKU {sku} 处理失败: {e}")
                            return None
                
            except Exception as e:
                logger.exception(f"SKU {sku} 处理异常: {e}")
                return None
    
    def _validate_and_fill_result(self, result: Dict):
        """验证并补全结果"""
        required_keys = {
            '产品名称', '产品描述',
            '产品卖点 1', '产品卖点 2', '产品卖点 3',
            '产品卖点 4', '产品卖点 5'
        }
        
        for key in required_keys:
            result.setdefault(key, '')

    @staticmethod
    def _build_detail_tuple(sku: str, product_type: str, content) -> Tuple:
        """Convert v2 generated content into the existing detail-table contract."""
        raw_payload = {
            "generator_version": "v2",
            "product_type": product_type,
            "title": content.title,
            "bullet_1": content.bullet_1,
            "bullet_2": content.bullet_2,
            "bullet_3": content.bullet_3,
            "bullet_4": content.bullet_4,
            "bullet_5": content.bullet_5,
            "description": content.description,
            "search_terms": content.search_terms,
            "generic_keyword": content.generic_keyword,
            "enriched_attributes": content.enriched_attributes,
            "validation_warnings": content.validation_warnings,
        }
        return (
            sku,
            content.title,
            content.bullet_1,
            content.bullet_2,
            content.bullet_3,
            content.bullet_4,
            content.bullet_5,
            content.description,
            "product_content_generator_v2",
            json.dumps(raw_payload, ensure_ascii=False),
        )
    
    def process_batch(self, sku_list: List[str]) -> int:
        """
        批量处理SKU
        
        Returns:
            成功处理的数量
        """
        batch_results = []
        
        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            futures = {
                executor.submit(self.process_single_sku, sku): sku 
                for sku in sku_list
            }
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        batch_results.append(result)
                except Exception as e:
                    sku = futures[future]
                    logger.error(f"SKU {sku} 线程执行异常: {e}")
        
        # 批量保存
        saved_count = self.repository.batch_save_details(batch_results)
        
        # 更新统计
        self.processed_count += saved_count
        self.failed_count += len(sku_list) - saved_count
        
        return saved_count
    
    def process_all_skus(self):
        """处理所有未处理的SKU"""
        logger.info("🚀 开始LLM商品详情生成流程...")
        
        # 1. 获取待处理SKU
        all_skus = self.repository.get_unprocessed_skus()
        
        if not all_skus:
            logger.info("✅ 没有需要处理的SKU")
            self.reporter.emit("✅ 没有需要处理的SKU")
            return
        
        total_skus = len(all_skus)
        num_batches = (total_skus + self.batch_size - 1) // self.batch_size
        
        logger.info(f"📊 待处理SKU总数: {total_skus}")
        self.reporter.emit(f"\n📊 待处理SKU总数: {total_skus}")
        self.reporter.emit(f"📦 批次大小: {self.batch_size}")
        self.reporter.emit(f"🧵 线程数: {self.thread_count}")
        self.reporter.emit(f"📏 最大输入长度: {self.max_input_length}字符\n")
        
        # 2. 分批处理
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.batch_size
            end_idx = min((batch_idx + 1) * self.batch_size, total_skus)
            batch_skus = all_skus[start_idx:end_idx]
            
            logger.info(f"🔄 处理批次 {batch_idx+1}/{num_batches}: {len(batch_skus)}个SKU")
            self.reporter.emit(f"🔄 处理批次 {batch_idx+1}/{num_batches}...")
            
            saved_count = self.process_batch(batch_skus)
            
            logger.info(f"✔️ 批次{batch_idx+1}完成: 成功{saved_count}个")
            self.reporter.emit(f"   ✔️ 成功: {saved_count}/{len(batch_skus)}")
            self.reporter.emit(f"   📈 总进度: {self.processed_count}/{total_skus}\n")
            
            time.sleep(0.5)  # 批次间隔
        
        # 3. 输出总结
        self.reporter.emit("\n" + "="*60)
        self.reporter.emit("✅ 处理完成！")
        self.reporter.emit("="*60)
        self.reporter.emit(f"成功: {self.processed_count}")
        self.reporter.emit(f"失败: {self.failed_count}")
        self.reporter.emit(f"总计: {total_skus}")
        self.reporter.emit("="*60 + "\n")
        
        logger.info(f"🎉 处理完成: {self.processed_count}成功 | {self.failed_count}失败")
