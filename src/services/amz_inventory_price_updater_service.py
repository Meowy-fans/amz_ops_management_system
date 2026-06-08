"""
Amazon Inventory & Price Updater Service
亚马逊库存和价格更新服务

生成亚马逊库存和价格更新文件的业务逻辑服务。
支持通过 SP-API patchListingsItem 直接更新价格和库存。
"""
import json
import logging
import os
import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from src.repositories.amz_listing_data_repository import ListingDataRepository
from src.services.giga_price_sync_service import GigaPriceSyncService
from src.services.giga_inventory_sync_service import GigaInventorySyncService
from src.services.pricing_service import PricingService
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class InventoryPriceUpdaterService:
    """
    生成亚马逊库存和价格更新文件的业务逻辑服务。
    
    流程：
    1. 同步最新的 Giga 价格数据
    2. 同步最新的 Giga 库存数据
    3. 更新系统内的商品售价
    4. 整合数据并生成更新文件
    """

    def __init__(
        self,
        db: Session,
        reporter: ProgressReporter | None = None,
        listings_client: Any = None,
        submission_repo: Any = None,
    ):
        self.db = db
        self.repository = ListingDataRepository(db)
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self._submission_repo_instance = submission_repo

    def _sync_latest_data(self):
        """
        调用现有的同步服务，确保数据最新。
        
        步骤：
        1. 同步 Giga 商品价格
        2. 同步 Giga 商品库存
        3. 更新系统售价
        """
        try:
            # 1. 同步价格
            self.reporter.emit("\n➡️ 步骤 1/4: 开始同步全量 Giga 商品价格...")
            logger.info("调用 GigaPriceSyncService...")
            price_service = GigaPriceSyncService(self.db, reporter=self.reporter)
            price_service.sync_all_prices()
            self.reporter.emit("✔️ 商品价格同步完成。")

            # 2. 同步库存
            self.reporter.emit("\n➡️ 步骤 2/4: 开始更新 Giga 已同步全量商品的库存...")
            logger.info("调用 GigaInventorySyncService...")
            inventory_service = GigaInventorySyncService(self.db, reporter=self.reporter)
            inventory_service.sync_all_inventory()
            self.reporter.emit("✔️ 商品库存更新完成。")

            # 3. 更新售价
            self.reporter.emit("\n➡️ 步骤 3/4: 开始批量更新所有商品售价...")
            logger.info("调用 PricingService...")
            pricing_service = PricingService(self.db, reporter=self.reporter)
            pricing_service.update_prices()
            self.reporter.emit("✔️ 商品售价更新完成。")
            
        except Exception as e:
            logger.error(f"数据同步阶段发生错误: {e}", exc_info=True)
            self.reporter.emit(f"❌ 数据同步阶段发生错误，但流程将继续尝试使用现有数据。")

    def generate_update_file(self):
        """
        执行完整的业务流程来生成更新文件。
        
        完整流程：
        1. 同步最新数据（价格、库存、售价）
        2. 获取需要更新的 SKU 映射
        3. 批量获取价格和库存数据
        4. 整合数据
        5. 生成制表符分隔的 .txt 文件
        """
        logger.info("🚀 启动生成亚马逊库存价格更新文件流程...")

        # 1. 调用同步服务
        self._sync_latest_data()

        # 2. 获取基础数据
        self.reporter.emit("\n➡️ 步骤 4/4: 正在整合数据并生成文件...")
        sku_map = self.repository.get_skus_for_update()
        
        if not sku_map:
            self.reporter.emit("✅ 未找到任何需要处理的商品，流程结束。")
            logger.info("未在数据库中找到任何符合条件的商品。")
            return

        # 提取所有唯一的 SKU
        amazon_skus = list(set(item['amazon_sku'] for item in sku_map))
        giga_skus = list(set(item['giga_sku'] for item in sku_map))

        # 3. 批量获取更新后的价格和库存
        price_map, quantity_map = self.repository.get_latest_data(
            amazon_skus, 
            giga_skus
        )

        # 4. 整合数据
        logger.info("开始整合最终数据...")
        final_data = []
        
        for item in sku_map:
            amazon_sku = item['amazon_sku']
            giga_sku = item['giga_sku']

            # 使用 .get() 方法安全地获取值，如果找不到则为 None
            price = price_map.get(amazon_sku)
            quantity = quantity_map.get(giga_sku)

            final_data.append({
                "sku": amazon_sku,
                "price": price,
                "minimum-seller-allowed-price": "",
                "maximum-seller-allowed-price": "",
                "quantity": quantity,
                "handling-time": "",
                "fulfillment-channel": ""
            })

        # 5. 生成文件
        logger.info("正在生成制表符分隔的文本文件...")
        try:
            df = pd.DataFrame(final_data)

            # 确保列的顺序符合亚马逊模板要求
            column_order = [
                "sku", 
                "price", 
                "minimum-seller-allowed-price",
                "maximum-seller-allowed-price", 
                "quantity", 
                "handling-time",
                "fulfillment-channel"
            ]
            df = df[column_order]

            # 处理NaN/None值，确保空字段是真正的空字符串
            df = df.fillna('')

            # ✅ 修复：正确处理 quantity 列的数据类型转换
            # 先转换为数值，然后转为字符串，没有库存信息的显示为 0
            df['quantity'] = (
                pd.to_numeric(df['quantity'], errors='coerce')  # 转换为数值，无效值变为 NaN
                .apply(lambda x: '0' if pd.isna(x) else str(int(x)))  # NaN 变 '0'，其他转整数再转字符串
            )

            # 文件保存路径
            output_dir = os.path.join(
                os.path.dirname(__file__), 
                '..', 
                '..', 
                'output'
            )
            os.makedirs(output_dir, exist_ok=True)
            
            filename = (
                f"AmazonPriceQuantityUpdate_"
                f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            filepath = os.path.join(output_dir, filename)

            # 保存为制表符分隔的 .txt 文件
            df.to_csv(filepath, sep='\t', index=False, header=True)

            self.reporter.emit("\n" + "=" * 70)
            self.reporter.emit("🎉 流程执行成功！")
            self.reporter.emit(f"📄 更新文件已成功保存至: {filepath}")
            self.reporter.emit(f"📊 共处理 {len(final_data)} 个商品")
            self.reporter.emit("=" * 70)
            logger.info(f"更新文件已成功保存至: {filepath}")

        except Exception as e:
            self.reporter.emit(f"❌ 生成文件时发生严重错误: {e}")
            logger.error(f"生成文件失败: {e}", exc_info=True)

    # ── SP-API submit path ──────────────────────────────────────────

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _submission_repository(self):
        if self._submission_repo_instance is not None:
            return self._submission_repo_instance
        from src.repositories.amazon_api_submission_repository import (
            AmazonAPISubmissionRepository,
        )

        self._submission_repo_instance = AmazonAPISubmissionRepository(self.db)
        return self._submission_repo_instance

    def _resolve_product_types(self, amazon_skus: List[str]) -> Dict[str, str]:
        """Map each Amazon SKU to its Amazon product type (CABINET, HOME_MIRROR, etc).

        Falls back to "PRODUCT" when no category mapping exists.
        """
        from src.repositories.category_repository import CategoryRepository

        cat_repo = CategoryRepository(self.db)
        raw = cat_repo.get_sku_to_category_mapping(amazon_skus)

        result: Dict[str, str] = {}
        for meow_sku, category_name in raw:
            if category_name:
                result[meow_sku] = category_name.upper()
        return result

    @staticmethod
    def _build_patches(
        sku: str,
        price: Optional[float],
        quantity: Optional[int],
        marketplace_id: str,
    ) -> List[Dict[str, Any]]:
        """Build RFC 6902 JSON Patch operations for price and/or quantity.

        Returns an empty list when neither price nor quantity is available.
        """
        patches: List[Dict[str, Any]] = []

        if price is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": "/attributes/purchasable_offer",
                    "value": [
                        {
                            "currency": "USD",
                            "our_price": [
                                {"schedule": [{"value_with_tax": float(price)}]}
                            ],
                            "marketplace_id": marketplace_id,
                        }
                    ],
                }
            )

        if quantity is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [
                        {
                            "fulfillment_channel_code": "DEFAULT",
                            "quantity": int(quantity),
                        }
                    ],
                }
            )

        return patches

    def submit_updates_via_api(self, dry_run: bool = True) -> List[Dict[str, Any]]:
        """Build patches and submit them via Listings Items API-native flow.

        Args:
            dry_run: If True, build patches and log without submitting.
        """
        logger.info("Starting API-native price/inventory update flow (dry_run=%s)", dry_run)
        from src.services.amazon_price_inventory_update_service import (
            AmazonPriceInventoryUpdateService,
        )

        service = AmazonPriceInventoryUpdateService(
            db=self.db,
            reporter=self.reporter,
            listings_client=self._listings_client_instance,
            submission_repo=self._submission_repo_instance,
            listing_data_repo=self.repository,
            sync_latest_data=self._sync_latest_data,
        )
        return service.submit_updates_via_api(dry_run=dry_run)
