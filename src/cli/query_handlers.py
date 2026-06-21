"""Read-only CLI query handlers."""
from sqlalchemy import text
from sqlalchemy.orm import Session


def handle_view_statistics(db: Session):
    """2.1 查看数据统计"""
    from src.repositories.giga_product_sync_repository import GigaProductSyncRepository
    from src.repositories.llm_product_detail_repository import LLMProductDetailRepository
    from src.repositories.sku_mapping_repository import SkuMappingRepository
    from src.repositories.giga_product_price_repository import GigaProductPriceRepository
    from src.repositories.giga_product_inventory_repository import GigaProductInventoryRepository
    from src.repositories.amz_full_list_report_repository import AmzFullListReportRepository

    print("\n" + "=" * 70)
    print("📊 数据统计")
    print("=" * 70)

    try:
        amz_repo = AmzFullListReportRepository(db)
        amz_stats = amz_repo.get_statistics()
        print("\n【Amazon数据】")
        print(f"  总记录: {amz_stats.get('total_records', amz_stats.get('total', 'N/A'))}")
        print(f"  Active: {amz_stats.get('active_listings', amz_stats.get('active', 'N/A'))}")
        print(f"  唯一ASIN: {amz_stats.get('unique_asins', 'N/A')}")
    except Exception as e:
        print(f"\n【Amazon数据】")
        print(f"  查询失败: {e}")

    try:
        giga_repo = GigaProductSyncRepository(db)
        giga_stats = giga_repo.get_statistics()
        print("\n【Giga商品】")
        print(f"  总记录: {giga_stats.get('total_products', giga_stats.get('total', 'N/A'))}")
        print(f"  已同步: {giga_stats.get('synced_products', 'N/A')}")
        print(f"  超大件: {giga_stats.get('oversized_products', 'N/A')}")
    except Exception as e:
        print(f"\n【Giga商品】")
        print(f"  查询失败: {e}")

    try:
        llm_repo = LLMProductDetailRepository(db)
        llm_stats = llm_repo.get_statistics()
        print("\n【LLM生成详情】")
        print(f"  总记录: {llm_stats.get('total_details', llm_stats.get('total', 'N/A'))}")
        print(f"  唯一SKU: {llm_stats.get('unique_skus', 'N/A')}")
    except Exception as e:
        print(f"\n【LLM生成详情】")
        print(f"  查询失败: {e}")

    try:
        mapping_repo = SkuMappingRepository(db)
        mapping_stats = mapping_repo.get_statistics()
        print("\n【SKU映射】")
        print(f"  总映射: {mapping_stats.get('total_mappings', mapping_stats.get('total', 'N/A'))}")
        print(f"  供应商数: {mapping_stats.get('unique_vendors', 'N/A')}")
    except Exception as e:
        print(f"\n【SKU映射】")
        print(f"  查询失败: {e}")

    try:
        price_repo = GigaProductPriceRepository(db)
        price_stats = price_repo.get_statistics()
        print("\n【Giga价格】")
        print(f"  总价格: {price_stats.get('total_prices', price_stats.get('total', 'N/A'))}")
        print(f"  可用SKU: {price_stats.get('available_skus', 'N/A')}")
        print(f"  价格梯度: {price_stats.get('total_tiers', 'N/A')}")
    except Exception as e:
        print(f"\n【Giga价格】")
        print(f"  查询失败: {e}")

    try:
        inventory_repo = GigaProductInventoryRepository(db)
        inventory_stats = inventory_repo.get_statistics()
        print("\n【Giga库存】")
        print(f"  总SKU: {inventory_stats.get('total_skus', 'N/A')}")
        print(f"  有库存: {inventory_stats.get('in_stock_skus', 'N/A')}")
        print(f"  总库存量: {inventory_stats.get('total_quantity', 'N/A')}")
    except Exception as e:
        print(f"\n【Giga库存】")
        print(f"  查询失败: {e}")

    print("=" * 70 + "\n")


def handle_pending_statistics(db: Session):
    """2.2 查看待发品统计"""
    from src.services.category_readiness_service import CategoryReadinessService

    print("\n" + "=" * 70)
    print("📊 待发品统计")
    print("=" * 70)

    try:
        rows = CategoryReadinessService(db).pending_counts()
        total = sum(row["pending_count"] for row in rows)

        print()
        print(f"   总待发品数: {total}")
        for row in rows:
            print(
                f"   - {row['product_type']}: {row['pending_count']} "
                f"({row['status']})"
            )
        print("=" * 70)

    except Exception as e:
        print(f"❌ 查询统计失败: {e}")


def handle_recent_listings(db: Session):
    """2.3 查看最近发品记录"""
    print("\n" + "=" * 70)
    print("📜 最近发品记录（最近10条）")
    print("=" * 70)

    try:
        query = text("""
            SELECT
                listing_batch_id,
                COUNT(*) as sku_count,
                COUNT(*) FILTER (WHERE parent_sku = 'SINGLE_PRODUCT') as single_count,
                COUNT(*) FILTER (WHERE parent_sku != 'SINGLE_PRODUCT') as variation_count,
                status,
                MIN(created_at) as created_at
            FROM amz_listing_log
            GROUP BY listing_batch_id, status
            ORDER BY created_at DESC
            LIMIT 10;
        """)

        result = db.execute(query).fetchall()

        if result:
            print()
            for i, row in enumerate(result, 1):
                batch_id = str(row[0])[:8]
                print(f"   {i}. 批次 {batch_id}... | SKU数: {row[1]} | 单品: {row[2]} | 变体: {row[3]} | 状态: {row[4]}")
                print(f"      时间: {row[5].strftime('%Y-%m-%d %H:%M:%S') if row[5] else 'N/A'}")
        else:
            print("   暂无发品记录")

        print("=" * 70)

    except Exception as e:
        print(f"❌ 查询记录失败: {e}")


def handle_list_categories(db: Session):
    """3.1 列出所有可用品类"""
    from src.services.category_readiness_service import CategoryReadinessService

    print("\n" + "=" * 70)
    print("📋 类目发品准备度")
    print("=" * 70)

    try:
        result = CategoryReadinessService(db).list_readiness()

        if result:
            print()
            for i, item in enumerate(result, 1):
                print(
                    f"   {i}. {item.product_type} | {item.status} | "
                    f"pending={item.pending_count} | mode={item.rule_mode} | "
                    f"schema={'yes' if item.schema_cached else 'no'}"
                )
                if item.missing_required_rules:
                    preview = ", ".join(item.missing_required_rules[:5])
                    more = (
                        f" (+{len(item.missing_required_rules) - 5})"
                        if len(item.missing_required_rules) > 5
                        else ""
                    )
                    print(f"      missing required rules: {preview}{more}")
            print(f"\n总计: {len(result)} 个品类")
        else:
            print("   暂无品类数据")

        print("=" * 70)

    except Exception as e:
        print(f"❌ 查询品类失败: {e}")
