"""
Classifier: assigns top_category and sub_category to GSTRecord instances
based on HSN chapter prefix rules and keyword overrides.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from gst_scraper.models import (
    ClassificationConfig,
    ClassificationRule,
    GSTRecord,
    SubCategory,
    TopCategory,
)

logger = logging.getLogger("gst_scraper.classifier")

# Default HSN chapter → category rules (used when no config provided)
_DEFAULT_HSN_RULES: list[dict[str, Any]] = [
    {"start": 1, "end": 5, "top": "consumer_goods", "sub": "animal_products"},
    {"start": 6, "end": 14, "top": "consumer_goods", "sub": "vegetable_products"},
    {"start": 15, "end": 24, "top": "consumer_goods", "sub": "food_beverages"},
    {"start": 25, "end": 27, "top": "industrial", "sub": "minerals_fuels"},
    {"start": 28, "end": 38, "top": "industrial", "sub": "chemicals_pharma"},
    {"start": 39, "end": 40, "top": "industrial", "sub": "plastics_rubber"},
    {"start": 41, "end": 43, "top": "consumer_goods", "sub": "leather_goods"},
    {"start": 44, "end": 49, "top": "industrial", "sub": "wood_paper"},
    {"start": 50, "end": 63, "top": "consumer_goods", "sub": "textiles_apparel"},
    {"start": 64, "end": 67, "top": "consumer_goods", "sub": "footwear_accessories"},
    {"start": 68, "end": 70, "top": "industrial", "sub": "construction_materials"},
    {"start": 71, "end": 71, "top": "consumer_goods", "sub": "jewelry"},
    {"start": 72, "end": 83, "top": "industrial", "sub": "metals"},
    {"start": 84, "end": 85, "top": "electronics", "sub": "computers_electronics"},
    {"start": 86, "end": 89, "top": "automotive", "sub": "vehicles_transport"},
    {"start": 90, "end": 92, "top": "electronics", "sub": "instruments"},
    {"start": 93, "end": 93, "top": "other", "sub": "arms_ammunition"},
    {"start": 94, "end": 96, "top": "consumer_goods", "sub": "furniture_misc"},
    {"start": 97, "end": 97, "top": "consumer_goods", "sub": "art_antiques"},
]

# Default keyword overrides
_DEFAULT_KEYWORD_OVERRIDES: dict[str, str] = {
    "mobile": "electronics",
    "smartphone": "electronics",
    "laptop": "electronics",
    "computer": "electronics",
    "television": "electronics",
    "tv": "electronics",
    "tablet": "electronics",
    "monitor": "electronics",
    "printer": "electronics",
    "camera": "electronics",
    "headphone": "electronics",
    "speaker": "electronics",
    "refrigerator": "electronics",
    "washing machine": "electronics",
    "air conditioner": "electronics",
    "microwave": "electronics",
    "fan": "electronics",
    "led": "electronics",
    "charger": "electronics",
    "battery": "electronics",
    "inverter": "electronics",
    "motor": "electronics",
    "transformer": "electronics",
    "cable": "electronics",
    "wire": "electronics",
    "car": "automotive",
    "motorcycle": "automotive",
    "scooter": "automotive",
    "tyre": "automotive",
    "tire": "automotive",
    "vehicle": "automotive",
    "automobile": "automotive",
    "tractor": "automotive",
    "engine": "automotive",
    "medicine": "consumer_goods",
    "pharmaceutical": "consumer_goods",
    "drug": "consumer_goods",
    "surgical": "consumer_goods",
    "fertilizer": "industrial",
    "cement": "industrial",
    "steel": "industrial",
    "iron": "industrial",
    "aluminium": "industrial",
    "copper": "industrial",
    "plastic": "industrial",
    "rubber": "industrial",
    "petroleum": "industrial",
    "coal": "industrial",
}

# Keyword → sub_category override
_KEYWORD_SUB_CATEGORY: dict[str, str] = {
    "mobile": "computers_electronics",
    "smartphone": "computers_electronics",
    "laptop": "computers_electronics",
    "computer": "computers_electronics",
    "television": "consumer_appliances",
    "tv": "consumer_appliances",
    "refrigerator": "consumer_appliances",
    "washing machine": "consumer_appliances",
    "air conditioner": "consumer_appliances",
    "microwave": "consumer_appliances",
    "fan": "consumer_appliances",
    "car": "vehicles_transport",
    "motorcycle": "vehicles_transport",
    "tractor": "vehicles_transport",
    "medicine": "chemicals_pharma",
    "pharmaceutical": "chemicals_pharma",
}


class Classifier:
    """
    Classifies GSTRecords into top_category and sub_category.

    Priority:
    1. Keyword overrides (highest — matches on description text)
    2. HSN chapter prefix rules (default fallback)
    """

    def __init__(self, config: ClassificationConfig | None = None):
        self.config = config

        # Build HSN rules
        if config and config.hsn_rules:
            self._hsn_rules = [
                {
                    "start": r.hsn_prefix_start,
                    "end": r.hsn_prefix_end,
                    "top": r.top_category.value if isinstance(r.top_category, TopCategory) else r.top_category,
                    "sub": r.sub_category.value if isinstance(r.sub_category, SubCategory) else r.sub_category,
                }
                for r in config.hsn_rules
            ]
        else:
            self._hsn_rules = _DEFAULT_HSN_RULES

        # Build keyword overrides
        if config and config.keyword_overrides:
            self._keyword_overrides = config.keyword_overrides
        else:
            self._keyword_overrides = _DEFAULT_KEYWORD_OVERRIDES

    def classify(self, records: list[GSTRecord]) -> list[GSTRecord]:
        """Classify a list of GSTRecords. Modifies records in-place and returns them."""
        distribution: dict[str, int] = {}

        for record in records:
            top, sub = self._classify_single(record)
            record.top_category = top
            record.sub_category = sub

            distribution[top] = distribution.get(top, 0) + 1

        logger.info(
            f"Classification complete: {distribution}",
            extra={"stage": "classify", "count": len(records)},
        )
        return records

    def _classify_single(self, record: GSTRecord) -> tuple[str, str]:
        """Classify a single record."""
        # Step 1: Check keyword overrides on description
        description_lower = record.gst_description.lower()
        for keyword, top_cat in self._keyword_overrides.items():
            if keyword in description_lower:
                sub_cat = _KEYWORD_SUB_CATEGORY.get(keyword, "uncategorized")
                return top_cat, sub_cat

        # Step 2: HSN prefix rules
        hsn = record.hsn_code
        if hsn and len(hsn) >= 2:
            try:
                chapter = int(hsn[:2])
                for rule in self._hsn_rules:
                    if rule["start"] <= chapter <= rule["end"]:
                        return rule["top"], rule["sub"]
            except ValueError:
                pass

        # Default
        return TopCategory.OTHER.value, SubCategory.UNCATEGORIZED.value

    def get_category_for_hsn(self, hsn_code: str) -> tuple[str, str]:
        """Get category for a given HSN code (utility method)."""
        if not hsn_code or len(hsn_code) < 2:
            return TopCategory.OTHER.value, SubCategory.UNCATEGORIZED.value

        try:
            chapter = int(hsn_code[:2])
            for rule in self._hsn_rules:
                if rule["start"] <= chapter <= rule["end"]:
                    return rule["top"], rule["sub"]
        except ValueError:
            pass

        return TopCategory.OTHER.value, SubCategory.UNCATEGORIZED.value
