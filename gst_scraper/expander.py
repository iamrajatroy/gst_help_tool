"""
Expander: generates product-level rows from base GST records.

Supports two modes:
- synthetic_mode: creates product variants from category-specific templates
- catalog_mode: enriches existing SKUs with GST mappings

Designed to generate 100,000+ rows with realistic, category-specific product names.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import random
import uuid
from typing import Any, Optional

import pandas as pd

from gst_scraper.models import ExpansionMode, GSTRecord, SubCategory

logger = logging.getLogger("gst_scraper.expander")

# ---------------------------------------------------------------------------
# Category-specific product templates for synthetic expansion
# Each template has: name_patterns, brands, variants
# ---------------------------------------------------------------------------

_PRODUCT_TEMPLATES: dict[str, dict[str, Any]] = {
    "animal_products": {
        "names": [
            "Fresh Chicken", "Mutton Leg", "Fish Fillet", "Prawns",
            "Eggs Pack", "Dairy Butter", "Paneer Block", "Cheese Slice",
            "Yogurt Cup", "Ghee Jar", "Milk Powder", "Honey Bottle",
            "Curd Tub", "Cream", "Whey Protein", "Casein Powder",
        ],
        "brands": ["FreshFarm", "DairyBest", "NaturePure", "AgroFresh", "OrganicValley",
                    "MilkyWay", "GreenMeadow", "PureDairy", "FarmHouse", "NutriLife"],
        "variants": ["500g", "1kg", "2kg", "250g", "100g", "5kg", "Pack of 6",
                      "Pack of 12", "Pack of 30", "Family Pack", "Premium", "Regular"],
    },
    "vegetable_products": {
        "names": [
            "Basmati Rice", "Wheat Flour", "Maize", "Soybean Oil",
            "Mustard Seeds", "Tea Leaves", "Coffee Beans", "Cashew Nuts",
            "Almonds", "Raisins", "Turmeric Powder", "Chili Powder",
            "Cardamom", "Pepper", "Ginger", "Garlic", "Cumin Seeds",
            "Coriander", "Fennel", "Saffron", "Dried Fruits Mix",
            "Sesame Seeds", "Flax Seeds", "Chia Seeds", "Quinoa",
        ],
        "brands": ["Nature's Basket", "Tata Sampann", "MDH", "Everest", "24 Mantra",
                    "Organic Tattva", "BB Royal", "Fortune", "Aashirvaad", "Patanjali",
                    "Daawat", "India Gate", "Kohinoor"],
        "variants": ["500g", "1kg", "5kg", "10kg", "25kg", "100g", "250g",
                      "Whole", "Ground", "Premium", "Regular", "Organic"],
    },
    "food_beverages": {
        "names": [
            "Refined Sugar", "Jaggery", "Biscuits", "Pasta", "Noodles",
            "Tomato Ketchup", "Mayonnaise", "Jam", "Pickle", "Sauce",
            "Chocolate Bar", "Candy", "Ice Cream", "Soft Drink", "Juice",
            "Energy Drink", "Mineral Water", "Bread", "Cake Mix",
            "Cornflakes", "Oats", "Muesli", "Peanut Butter", "Olive Oil",
            "Vinegar", "Soy Sauce", "Chips", "Namkeen", "Papad",
            "Ready to Eat Meal", "Frozen Food", "Canned Food",
        ],
        "brands": ["Britannia", "Parle", "ITC", "Nestle", "Amul", "Haldirams",
                    "MTR", "Kissan", "Maggi", "Cadbury", "PepsiCo", "Coca-Cola",
                    "Tropicana", "Real", "Bisleri", "Lays", "Kurkure"],
        "variants": ["100g", "200g", "500g", "1kg", "1L", "500ml", "2L",
                      "Family Pack", "Mini Pack", "Value Pack", "Multipack",
                      "Original", "Classic", "Spicy", "Sweet", "Sugar-Free"],
    },
    "minerals_fuels": {
        "names": [
            "Portland Cement Clinker", "Natural Sand", "Marble Slab",
            "Granite Block", "Crude Petroleum", "Natural Gas", "Coal",
            "Lignite", "Bituminous Coal", "Mineral Water Source",
            "Limestone", "Chalk", "Quartz", "Feldspar", "Mica",
            "Salt", "Sulphur", "Graphite", "Asbestos",
        ],
        "brands": ["IndiaMineral", "GeoCorp", "MineralEx", "NaturalRes",
                    "GeoTech", "RockSolid", "EarthCore", "MinePro"],
        "variants": ["Per Tonne", "Per MT", "Bulk", "Refined", "Crude",
                      "Processed", "Raw", "Grade A", "Grade B", "Industrial Grade"],
    },
    "chemicals_pharma": {
        "names": [
            "Paracetamol Tablet", "Amoxicillin Capsule", "Aspirin",
            "Ibuprofen", "Vitamin C", "Calcium Supplement", "Insulin",
            "Hand Sanitizer", "Surgical Mask", "Bandage", "Cotton Roll",
            "Antiseptic Liquid", "Cough Syrup", "Eye Drops", "Ointment",
            "Sulphuric Acid", "Hydrochloric Acid", "Sodium Hydroxide",
            "Ammonia", "Hydrogen Peroxide", "Chlorine", "Ethanol",
            "Methanol", "Acetone", "Formaldehyde", "Glycerine",
            "Detergent Powder", "Soap Bar", "Shampoo", "Toothpaste",
            "Face Wash", "Sunscreen", "Moisturizer", "Hair Oil",
            "Perfume", "Deodorant", "Nail Polish",
        ],
        "brands": ["Cipla", "Sun Pharma", "Dr Reddy's", "Lupin", "Ranbaxy",
                    "Dettol", "Savlon", "Lifebuoy", "Dove", "Lux",
                    "Colgate", "Pepsodent", "Head & Shoulders", "Pantene",
                    "Himalaya", "Dabur", "Marico", "Emami"],
        "variants": ["10 Tablets", "20 Tablets", "Strip", "Bottle 100ml",
                      "Bottle 200ml", "500ml", "1L", "5L",
                      "50g", "100g", "200g", "500g", "Tube", "Jar"],
    },
    "plastics_rubber": {
        "names": [
            "PVC Pipe", "HDPE Sheet", "Polythene Bag", "Plastic Container",
            "Rubber Sheet", "Silicone Sealant", "Nylon Rope", "Acrylic Sheet",
            "Polypropylene Granules", "PET Bottle Preform", "Rubber Gasket",
            "Vinyl Flooring", "Polyester Film", "Shrink Wrap",
            "Bubble Wrap", "Garbage Bag", "Tarpaulin",
        ],
        "brands": ["Supreme", "Astral", "Finolex", "Prince Pipes", "APL Apollo",
                    "PlastIndia", "PolyFlex", "RubberTech"],
        "variants": ["1m", "5m", "10m", "25m", "50m", "1kg", "5kg",
                      "Small", "Medium", "Large", "XL", "Roll",
                      "Sheet", "Per Piece", "Per Bundle"],
    },
    "leather_goods": {
        "names": [
            "Leather Wallet", "Leather Belt", "Leather Bag", "Leather Jacket",
            "Leather Shoes", "Leather Gloves", "Leather Purse", "Leather Briefcase",
            "Suede Boots", "Leather Watch Strap", "Passport Holder",
            "Leather Phone Case", "Leather Journal",
        ],
        "brands": ["Hidesign", "Wildcraft", "Woodland", "Leather Talks",
                    "Da Milano", "Holii", "Caprese", "Lavie"],
        "variants": ["Black", "Brown", "Tan", "Burgundy", "Navy",
                      "Small", "Medium", "Large", "Men's", "Women's",
                      "Genuine Leather", "Full Grain", "Top Grain"],
    },
    "wood_paper": {
        "names": [
            "A4 Copy Paper", "Printing Paper", "Cardboard Box", "Notebook",
            "Tissue Paper", "Kraft Paper", "Newspaper", "Magazine",
            "Book", "Plywood Sheet", "MDF Board", "Particle Board",
            "Bamboo Plank", "Cork Sheet", "Envelope", "File Folder",
            "Sticky Notes", "Diary", "Calendar", "Gift Wrap",
        ],
        "brands": ["JK Paper", "ITC Classmate", "Navneet", "Century Ply",
                    "GreenPly", "Kitply", "PaperOne", "Double A"],
        "variants": ["Ream 500", "Pack 100", "A4", "A3", "Legal Size",
                      "4mm", "6mm", "8mm", "12mm", "18mm",
                      "Single", "Pack of 5", "Pack of 10", "Bundle"],
    },
    "textiles_apparel": {
        "names": [
            "Cotton T-Shirt", "Polyester Shirt", "Silk Saree", "Denim Jeans",
            "Linen Kurta", "Wool Sweater", "Nylon Jacket", "Sports Jersey",
            "Formal Trousers", "Casual Shorts", "Cotton Bedsheet",
            "Bath Towel", "Curtain Fabric", "Carpet", "Doormat",
            "Socks Pair", "Undergarments", "Scarf", "Dupatta",
            "Shawl", "Blanket", "Pillow Cover", "Cushion Cover",
            "Table Cloth", "Handkerchief", "Tie", "Dhoti",
            "Lungi", "Tracksuit", "Hoodie", "Sweatshirt",
        ],
        "brands": ["Raymond", "Peter England", "Allen Solly", "Louis Philippe",
                    "Van Heusen", "Biba", "W", "Fabindia", "Manyavar",
                    "Jockey", "Levi's", "H&M", "Zara", "Uniqlo",
                    "Bombay Dyeing", "Welspun", "Trident"],
        "variants": ["S", "M", "L", "XL", "XXL", "28", "30", "32", "34", "36",
                      "White", "Blue", "Black", "Red", "Green", "Pink",
                      "Single", "Double", "Queen", "King",
                      "Cotton", "Blend", "Pure", "Printed", "Plain"],
    },
    "footwear_accessories": {
        "names": [
            "Running Shoes", "Formal Shoes", "Sandals", "Slippers",
            "Boots", "Sneakers", "Loafers", "Sports Shoes",
            "Heels", "Flats", "Flip Flops", "Moccasins",
            "Umbrella", "Cap", "Hat", "Sunglasses",
        ],
        "brands": ["Bata", "Relaxo", "Liberty", "Nike", "Adidas", "Puma",
                    "Reebok", "Skechers", "Woodland", "Red Tape",
                    "Metro", "Mochi"],
        "variants": ["6", "7", "8", "9", "10", "11", "12",
                      "Black", "Brown", "White", "Blue", "Red",
                      "Men's", "Women's", "Kids"],
    },
    "construction_materials": {
        "names": [
            "Ceramic Tiles", "Vitrified Tiles", "Glass Sheet",
            "Safety Glass", "Marble Tile", "Granite Slab",
            "Sandstone", "Slate", "Brick", "Building Block",
            "Concrete Block", "Paver Block", "Porcelain Tile",
            "Mirror", "Glass Jar", "Glass Bottle",
        ],
        "brands": ["Kajaria", "Somany", "Asian Granito", "RAK Ceramics",
                    "Johnson Tiles", "Nitco", "Orient Bell",
                    "Saint-Gobain", "Asahi Glass"],
        "variants": ["2x2 ft", "1x1 ft", "2x4 ft", "4x4 ft",
                      "6mm", "8mm", "10mm", "12mm",
                      "Glossy", "Matte", "Satin", "Anti-Skid",
                      "White", "Beige", "Grey"],
    },
    "jewelry": {
        "names": [
            "Gold Necklace", "Silver Ring", "Diamond Earring",
            "Gold Bangle", "Silver Chain", "Pearl Pendant",
            "Platinum Ring", "Gold Coin", "Silver Coin",
            "Gemstone Bracelet", "Gold Mangalsutra", "Nose Pin",
            "Toe Ring", "Anklet", "Brooch",
        ],
        "brands": ["Tanishq", "Malabar Gold", "Kalyan Jewellers",
                    "PC Jeweller", "Senco Gold", "Jos Alukkas",
                    "Joyalukkas", "CaratLane", "BlueStone"],
        "variants": ["22K", "24K", "18K", "14K", "Sterling Silver",
                      "1 gram", "2 gram", "5 gram", "10 gram", "50 gram",
                      "Hallmarked", "BIS Certified"],
    },
    "metals": {
        "names": [
            "Steel Rod", "Iron Sheet", "Aluminium Coil", "Copper Wire",
            "Zinc Ingot", "Brass Fitting", "Stainless Steel Pipe",
            "TMT Bar", "Angle Iron", "Steel Plate", "GI Pipe",
            "MS Channel", "Steel Beam", "Wire Nail", "Bolt Nut Set",
            "Rivet", "Spring", "Chain Link", "Welding Rod",
        ],
        "brands": ["Tata Steel", "JSW Steel", "SAIL", "Hindalco",
                    "Vedanta", "Jindal Steel", "APL Apollo", "Essar Steel",
                    "NALCO", "NMDC"],
        "variants": ["8mm", "10mm", "12mm", "16mm", "20mm", "25mm",
                      "Per Kg", "Per Tonne", "Per Meter", "Per Piece",
                      "Grade 304", "Grade 316", "MS", "SS", "GI"],
    },
    "computers_electronics": {
        "names": [
            "Smartphone", "Laptop", "Desktop Computer", "Tablet",
            "Smart TV", "LED Monitor", "Wireless Mouse", "Keyboard",
            "External Hard Drive", "SSD", "RAM Module", "Processor",
            "Graphics Card", "Motherboard", "Power Supply", "UPS",
            "Printer", "Scanner", "Webcam", "Microphone",
            "Bluetooth Speaker", "Wireless Earbuds", "Headphones",
            "Smartwatch", "Fitness Band", "Power Bank",
            "USB Cable", "HDMI Cable", "Charger", "Adapter",
            "Router", "Modem", "Switch Hub", "Projector",
        ],
        "brands": ["Samsung", "Apple", "HP", "Dell", "Lenovo", "Asus",
                    "Acer", "LG", "Sony", "OnePlus", "Xiaomi", "Realme",
                    "Oppo", "Vivo", "Nokia", "Motorola", "JBL", "Boat",
                    "Logitech", "Corsair", "Intel", "AMD"],
        "variants": ["4GB", "8GB", "16GB", "32GB", "64GB", "128GB", "256GB",
                      "512GB", "1TB", "2TB",
                      "Black", "White", "Silver", "Blue", "Red",
                      "Pro", "Max", "Ultra", "Lite", "Mini",
                      "Wi-Fi", "5G", "4G", "Bluetooth 5.0"],
    },
    "consumer_appliances": {
        "names": [
            "Refrigerator", "Washing Machine", "Air Conditioner",
            "Microwave Oven", "Ceiling Fan", "Table Fan", "Air Cooler",
            "Water Purifier", "Vacuum Cleaner", "Mixer Grinder",
            "Food Processor", "Electric Kettle", "Iron Press",
            "Induction Cooktop", "Gas Stove", "Chimney",
            "Geyser", "Air Purifier", "Dishwasher", "Toaster",
            "Electric Rice Cooker", "Juicer", "Hand Blender",
        ],
        "brands": ["LG", "Samsung", "Whirlpool", "Godrej", "Bosch",
                    "IFB", "Havells", "Bajaj", "Crompton", "Orient",
                    "Voltas", "Daikin", "Blue Star", "Kent",
                    "Eureka Forbes", "Prestige", "Butterfly", "Pigeon"],
        "variants": ["3 Star", "4 Star", "5 Star", "Inverter",
                      "1 Ton", "1.5 Ton", "2 Ton",
                      "Single Door", "Double Door", "Side-by-Side",
                      "Front Load", "Top Load", "Semi-Automatic",
                      "Small", "Medium", "Large",
                      "White", "Silver", "Grey", "Black"],
    },
    "vehicles_transport": {
        "names": [
            "Car", "Motorcycle", "Scooter", "Auto Rickshaw",
            "Bus", "Truck", "Bicycle", "Electric Scooter",
            "Electric Car", "Tractor", "Trailer",
            "Car Tyre", "Bike Tyre", "Car Battery",
            "Brake Pad", "Air Filter", "Oil Filter", "Spark Plug",
            "Headlight Bulb", "Side Mirror", "Wiper Blade",
            "Car Seat Cover", "Floor Mat",
        ],
        "brands": ["Maruti Suzuki", "Hyundai", "Honda", "Toyota",
                    "Tata Motors", "Mahindra", "Bajaj", "Hero",
                    "TVS", "Royal Enfield", "Yamaha", "Suzuki",
                    "MRF", "CEAT", "Apollo", "JK Tyre",
                    "Amaron", "Exide", "Bosch"],
        "variants": ["Petrol", "Diesel", "CNG", "Electric", "Hybrid",
                      "Manual", "Automatic", "Base", "Mid", "Top",
                      "Tubeless", "With Tube",
                      "OEM", "Aftermarket", "Compatible"],
    },
    "instruments": {
        "names": [
            "Digital Multimeter", "Oscilloscope", "Microscope",
            "Telescope", "Binoculars", "Thermometer",
            "Blood Pressure Monitor", "Stethoscope", "Weighing Scale",
            "Wall Clock", "Wrist Watch", "Alarm Clock",
            "Guitar", "Keyboard Piano", "Tabla", "Harmonium",
            "Flute", "Violin", "Sitar", "Drums",
        ],
        "brands": ["Casio", "Seiko", "Titan", "Fastrack", "Timex",
                    "Omron", "Dr Morepen", "Yamaha", "Roland", "Fender",
                    "Gibson", "Bose", "Nikon", "Canon"],
        "variants": ["Analog", "Digital", "Automatic",
                      "Beginner", "Intermediate", "Professional",
                      "Small", "Medium", "Large",
                      "Steel", "Leather", "Silicone"],
    },
    "arms_ammunition": {
        "names": [
            "Air Rifle", "Hunting Rifle", "Cartridge",
            "Ammunition Box", "Gun Case", "Holster",
            "Binocular Scope", "Gun Cleaning Kit",
        ],
        "brands": ["GenArms", "SafeShot", "ArmsTech", "IndoDefence"],
        "variants": ["Standard", "Premium", "Professional", "Licensed"],
    },
    "furniture_misc": {
        "names": [
            "Office Chair", "Dining Table", "Sofa Set", "Bed Frame",
            "Wardrobe", "Bookshelf", "Coffee Table", "Study Desk",
            "TV Unit", "Shoe Rack", "Kitchen Cabinet",
            "Mattress", "Pillow", "Bean Bag",
            "Cricket Bat", "Football", "Badminton Racket", "Tennis Ball",
            "Yoga Mat", "Dumbbell Set", "Treadmill", "Cycle Trainer",
            "Board Game", "Puzzle Set", "Building Blocks", "Doll",
            "Action Figure", "Toy Car", "Remote Control Car",
            "Pen", "Pencil", "Eraser", "Sharpener", "Ruler",
            "Candle", "Incense Stick", "Room Freshener", "Broom",
            "Mop", "Dustbin",
        ],
        "brands": ["Godrej Interio", "Urban Ladder", "Pepperfry", "IKEA",
                    "Nilkamal", "Durian", "Sleepwell", "Wakefit",
                    "SG", "Cosco", "Nivia", "Yonex", "Li-Ning",
                    "Cello", "Camlin", "DOMS", "Faber-Castell"],
        "variants": ["Single", "Double", "Queen", "King",
                      "Wood", "Metal", "Plastic", "Fabric",
                      "Walnut", "Oak", "Teak", "Pine",
                      "2-Seater", "3-Seater", "4-Seater", "L-Shape",
                      "Size 3", "Size 5", "Size 7",
                      "Beginner", "Pro", "Competition"],
    },
    "art_antiques": {
        "names": [
            "Oil Painting", "Watercolor Painting", "Canvas Art",
            "Sculpture", "Bronze Statue", "Marble Figure",
            "Antique Vase", "Handmade Pottery", "Art Print",
            "Photo Frame", "Wall Hanging", "Decorative Plate",
        ],
        "brands": ["ArtIndia", "CraftVilla", "IndianArtGallery",
                    "HandiCraft", "ArtFusion", "CreativeArts"],
        "variants": ["Small", "Medium", "Large", "Extra Large",
                      "Framed", "Unframed", "Limited Edition",
                      "Original", "Replica", "Handmade"],
    },
    "machinery": {
        "names": [
            "CNC Machine", "Lathe Machine", "Drilling Machine",
            "Welding Machine", "Compressor", "Generator",
            "Electric Motor", "Pump", "Conveyor Belt",
            "Industrial Oven", "Boiler", "Heat Exchanger",
            "Hydraulic Press", "Packaging Machine", "Sewing Machine",
        ],
        "brands": ["Siemens", "ABB", "Schneider", "Crompton", "Kirloskar",
                    "Mahindra", "Cummins", "Honda Power", "Bosch"],
        "variants": ["1HP", "2HP", "5HP", "10HP", "20HP", "50HP",
                      "Single Phase", "Three Phase",
                      "Automatic", "Semi-Automatic", "Manual",
                      "Portable", "Stationary", "Industrial Grade"],
    },
}


class Expander:
    """
    Generates product-level rows from base GST records.

    In synthetic mode, creates realistic product variants using
    category-specific name templates, brands, and variant attributes.
    """

    def __init__(
        self,
        mode: ExpansionMode | str = ExpansionMode.SYNTHETIC,
        target_rows: int = 100_000,
        catalog_path: Optional[str] = None,
    ):
        if isinstance(mode, str):
            mode = ExpansionMode(mode)
        self.mode = mode
        self.target_rows = target_rows
        self.catalog_path = catalog_path
        self._rng = random.Random(42)  # Reproducible randomness

    def expand(self, records: list[GSTRecord]) -> list[GSTRecord]:
        """
        Expand base records to target row count.

        Args:
            records: normalized and classified base GST records

        Returns:
            Expanded list of product-level GSTRecords
        """
        if self.mode == ExpansionMode.CATALOG:
            return self._expand_catalog(records)
        else:
            return self._expand_synthetic(records)

    # ------------------------------------------------------------------
    # Synthetic expansion
    # ------------------------------------------------------------------

    def _expand_synthetic(self, records: list[GSTRecord]) -> list[GSTRecord]:
        """Generate synthetic product variants to reach target_rows."""
        if not records:
            logger.warning("No base records to expand")
            return []

        # Group records by sub_category
        by_category: dict[str, list[GSTRecord]] = {}
        for rec in records:
            sub = rec.sub_category
            if sub not in by_category:
                by_category[sub] = []
            by_category[sub].append(rec)

        # Calculate expansion per category (proportional)
        total_base = len(records)
        expanded: list[GSTRecord] = []

        for sub_cat, cat_records in by_category.items():
            proportion = len(cat_records) / total_base
            cat_target = max(int(self.target_rows * proportion), len(cat_records))

            # Get templates for this sub_category
            templates = _PRODUCT_TEMPLATES.get(sub_cat, _PRODUCT_TEMPLATES.get("furniture_misc"))

            if templates:
                cat_expanded = self._generate_variants(cat_records, templates, cat_target)
            else:
                # No template — just duplicate with index
                cat_expanded = self._simple_expand(cat_records, cat_target)

            expanded.extend(cat_expanded)

        # Trim or pad to target
        if len(expanded) > self.target_rows:
            self._rng.shuffle(expanded)
            expanded = expanded[:self.target_rows]
        elif len(expanded) < self.target_rows:
            # Pad with more from largest categories
            deficit = self.target_rows - len(expanded)
            all_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)
            idx = 0
            while deficit > 0 and all_cats:
                cat_name, cat_recs = all_cats[idx % len(all_cats)]
                templates = _PRODUCT_TEMPLATES.get(cat_name, _PRODUCT_TEMPLATES.get("furniture_misc"))
                extra = self._generate_variants(cat_recs, templates, min(deficit, 1000))
                expanded.extend(extra)
                deficit -= len(extra)
                idx += 1

            expanded = expanded[:self.target_rows]

        logger.info(
            f"Synthetic expansion complete: {len(expanded)} rows "
            f"(target: {self.target_rows})",
            extra={"stage": "expand", "count": len(expanded)},
        )
        return expanded

    def _generate_variants(
        self,
        base_records: list[GSTRecord],
        templates: dict[str, Any],
        target: int,
    ) -> list[GSTRecord]:
        """Generate product variants for a category."""
        expanded = []
        names = templates.get("names", ["Product"])
        brands = templates.get("brands", ["Brand"])
        variants = templates.get("variants", ["Standard"])

        # Create all combinations
        combos = list(itertools.product(brands, names, variants))
        self._rng.shuffle(combos)

        combo_idx = 0
        record_idx = 0

        while len(expanded) < target:
            if combo_idx >= len(combos):
                combo_idx = 0
                self._rng.shuffle(combos)

            brand, name, variant = combos[combo_idx]
            base = base_records[record_idx % len(base_records)]

            product_name = f"{brand} {name} - {variant}"
            product_id = hashlib.sha256(
                f"{product_name}|{base.hsn_code}|{len(expanded)}".encode()
            ).hexdigest()[:16]

            new_record = GSTRecord(
                product_id=product_id,
                product_name=product_name,
                top_category=base.top_category,
                sub_category=base.sub_category,
                hsn_code=base.hsn_code,
                gst_description=base.gst_description,
                schedule=base.schedule,
                serial_no=base.serial_no,
                cgst_rate=base.cgst_rate,
                sgst_rate=base.sgst_rate,
                igst_rate=base.igst_rate,
                cess_rate=base.cess_rate,
                effective_from=base.effective_from,
                source_name=base.source_name,
                source_url=base.source_url,
                raw_text=base.raw_text,
                confidence_flag=base.confidence_flag,
            )
            expanded.append(new_record)
            combo_idx += 1
            record_idx += 1

        return expanded

    def _simple_expand(self, records: list[GSTRecord], target: int) -> list[GSTRecord]:
        """Simple expansion by appending index numbers."""
        expanded = []
        idx = 0
        while len(expanded) < target:
            base = records[idx % len(records)]
            new_record = GSTRecord(
                product_id=hashlib.sha256(f"{base.hsn_code}|{idx}".encode()).hexdigest()[:16],
                product_name=f"{base.gst_description} - Variant {idx + 1}",
                top_category=base.top_category,
                sub_category=base.sub_category,
                hsn_code=base.hsn_code,
                gst_description=base.gst_description,
                schedule=base.schedule,
                serial_no=base.serial_no,
                cgst_rate=base.cgst_rate,
                sgst_rate=base.sgst_rate,
                igst_rate=base.igst_rate,
                cess_rate=base.cess_rate,
                effective_from=base.effective_from,
                source_name=base.source_name,
                source_url=base.source_url,
                raw_text=base.raw_text,
                confidence_flag=base.confidence_flag,
            )
            expanded.append(new_record)
            idx += 1
        return expanded

    # ------------------------------------------------------------------
    # Catalog expansion
    # ------------------------------------------------------------------

    def _expand_catalog(self, records: list[GSTRecord]) -> list[GSTRecord]:
        """Enrich catalog SKUs with GST rate data."""
        if not self.catalog_path:
            logger.warning("No catalog input path specified, falling back to synthetic mode")
            return self._expand_synthetic(records)

        try:
            catalog_df = pd.read_csv(self.catalog_path)
        except Exception as e:
            logger.error(f"Failed to read catalog file: {e}")
            return self._expand_synthetic(records)

        # Build HSN → record lookup
        hsn_lookup: dict[str, GSTRecord] = {}
        for rec in records:
            if rec.hsn_code:
                hsn_lookup[rec.hsn_code] = rec

        expanded = []
        for _, row in catalog_df.iterrows():
            sku_hsn = str(row.get("hsn_code", "")).strip()
            sku_name = str(row.get("product_name", "")).strip()

            # Try exact match, then prefix match
            match = hsn_lookup.get(sku_hsn)
            if not match:
                for hsn, rec in hsn_lookup.items():
                    if sku_hsn.startswith(hsn[:4]):
                        match = rec
                        break

            if match:
                new_record = GSTRecord(
                    product_id=hashlib.sha256(f"catalog|{sku_name}|{sku_hsn}".encode()).hexdigest()[:16],
                    product_name=sku_name,
                    top_category=match.top_category,
                    sub_category=match.sub_category,
                    hsn_code=sku_hsn or match.hsn_code,
                    gst_description=match.gst_description,
                    cgst_rate=match.cgst_rate,
                    sgst_rate=match.sgst_rate,
                    igst_rate=match.igst_rate,
                    cess_rate=match.cess_rate,
                    source_name=match.source_name,
                    source_url=match.source_url,
                    raw_text=match.raw_text,
                    confidence_flag=match.confidence_flag,
                )
                expanded.append(new_record)

        logger.info(
            f"Catalog expansion: matched {len(expanded)} / {len(catalog_df)} SKUs",
            extra={"stage": "expand", "count": len(expanded)},
        )
        return expanded
