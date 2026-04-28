"""Tests for the Classifier module."""

from decimal import Decimal

import pytest

from gst_scraper.classifier import Classifier
from gst_scraper.models import GSTRecord, TopCategory, SubCategory


class TestHSNClassification:
    """Test HSN chapter prefix → category classification."""

    @pytest.fixture
    def classifier(self) -> Classifier:
        return Classifier()

    @pytest.mark.parametrize("hsn,expected_top,expected_sub", [
        ("0102", "consumer_goods", "animal_products"),
        ("0301", "consumer_goods", "animal_products"),
        ("0701", "consumer_goods", "vegetable_products"),
        ("1006", "consumer_goods", "vegetable_products"),
        ("1501", "consumer_goods", "food_beverages"),
        ("2106", "consumer_goods", "food_beverages"),
        ("2501", "industrial", "minerals_fuels"),
        ("2710", "industrial", "minerals_fuels"),
        ("2801", "industrial", "chemicals_pharma"),
        ("3304", "industrial", "chemicals_pharma"),
        ("3401", "industrial", "chemicals_pharma"),
        ("3901", "industrial", "plastics_rubber"),
        ("4001", "industrial", "plastics_rubber"),
        ("4101", "consumer_goods", "leather_goods"),
        ("4202", "consumer_goods", "leather_goods"),
        ("4401", "industrial", "wood_paper"),
        ("4801", "industrial", "wood_paper"),
        ("5001", "consumer_goods", "textiles_apparel"),
        ("6109", "consumer_goods", "textiles_apparel"),
        ("6401", "consumer_goods", "footwear_accessories"),
        ("6601", "consumer_goods", "footwear_accessories"),
        ("6801", "industrial", "construction_materials"),
        ("7001", "industrial", "construction_materials"),
        ("7101", "consumer_goods", "jewelry"),
        ("7113", "consumer_goods", "jewelry"),
        ("7201", "industrial", "metals"),
        ("7308", "industrial", "metals"),
        ("8301", "industrial", "metals"),
        ("8401", "electronics", "computers_electronics"),
        ("8517", "electronics", "computers_electronics"),
        ("8601", "automotive", "vehicles_transport"),
        ("8703", "automotive", "vehicles_transport"),
        ("8711", "automotive", "vehicles_transport"),
        ("9001", "electronics", "instruments"),
        ("9101", "electronics", "instruments"),
        ("9201", "electronics", "instruments"),
        ("9301", "other", "arms_ammunition"),
        ("9401", "consumer_goods", "furniture_misc"),
        ("9503", "consumer_goods", "furniture_misc"),
        ("9701", "consumer_goods", "art_antiques"),
    ])
    def test_hsn_prefix_classification(self, classifier, hsn, expected_top, expected_sub):
        top, sub = classifier.get_category_for_hsn(hsn)
        assert top == expected_top, f"HSN {hsn}: expected {expected_top}, got {top}"
        assert sub == expected_sub, f"HSN {hsn}: expected {expected_sub}, got {sub}"

    def test_unknown_hsn_returns_other(self, classifier):
        top, sub = classifier.get_category_for_hsn("9900")
        assert top == "other"
        assert sub == "uncategorized"

    def test_empty_hsn_returns_other(self, classifier):
        top, sub = classifier.get_category_for_hsn("")
        assert top == "other"

    def test_short_hsn_returns_other(self, classifier):
        top, sub = classifier.get_category_for_hsn("1")
        assert top == "other"


class TestKeywordOverrides:
    """Test keyword-based classification overrides."""

    @pytest.fixture
    def classifier(self) -> Classifier:
        return Classifier()

    def test_mobile_keyword(self, classifier):
        record = GSTRecord(
            hsn_code="3926",  # Plastics chapter, normally "industrial"
            gst_description="Mobile phone protective cover",
        )
        records = classifier.classify([record])
        assert records[0].top_category == "electronics"

    def test_laptop_keyword(self, classifier):
        record = GSTRecord(
            hsn_code="4202",  # Leather, normally "consumer_goods"
            gst_description="Laptop bag made of leather",
        )
        records = classifier.classify([record])
        assert records[0].top_category == "electronics"

    def test_car_keyword(self, classifier):
        record = GSTRecord(
            hsn_code="4011",  # Rubber, normally "industrial"
            gst_description="Car tyres, new pneumatic",
        )
        records = classifier.classify([record])
        assert records[0].top_category == "automotive"


class TestBatchClassification:
    """Test batch classification."""

    def test_classify_batch(self, sample_gst_records):
        classifier = Classifier()
        classified = classifier.classify(sample_gst_records)
        assert len(classified) == len(sample_gst_records)

        # All should have valid categories
        valid_tops = {e.value for e in TopCategory}
        for rec in classified:
            top = rec.top_category if isinstance(rec.top_category, str) else rec.top_category.value
            assert top in valid_tops
