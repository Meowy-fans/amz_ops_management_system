"""Select approved image assets for Amazon listing payloads."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class SelectedListingImages:
    main_image_url: str = ""
    other_image_urls: List[str] = field(default_factory=list)


class AmazonListingImageSelector:
    """Returns images that are allowed to be used in listing payloads.

    The selector is deliberately strict: only approved and auto_approved assets
    can enter live listing payloads. needs_review assets are visible for human
    workflows but are not selected here.
    """

    ALLOWED_STATUSES = {"approved", "auto_approved"}

    def __init__(self, image_asset_repo):
        self.image_asset_repo = image_asset_repo

    def get_approved_images(self, sku: str) -> SelectedListingImages:
        assets = self.image_asset_repo.get_assets_for_sku(sku)
        usable = [asset for asset in assets if asset.get("review_status") in self.ALLOWED_STATUSES]

        main = self._select_main(usable)
        others = []
        for asset in usable:
            url = self._asset_url(asset)
            if not url or url == main:
                continue
            others.append(url)
            if len(others) >= 8:
                break

        return SelectedListingImages(main_image_url=main, other_image_urls=others)

    def has_approved_main_image(self, sku: str) -> bool:
        return bool(self.get_approved_images(sku).main_image_url)

    def _select_main(self, assets) -> str:
        for status in ("approved", "auto_approved"):
            for asset in assets:
                if asset.get("review_status") == status and asset.get("slot") == "main":
                    return self._asset_url(asset)
        for status in ("approved", "auto_approved"):
            for asset in assets:
                if asset.get("review_status") == status:
                    return self._asset_url(asset)
        return ""

    @staticmethod
    def _asset_url(asset) -> str:
        return str(asset.get("storage_url") or asset.get("source_url") or "").strip()
