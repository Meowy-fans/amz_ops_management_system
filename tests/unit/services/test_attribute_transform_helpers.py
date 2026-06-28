from src.services.attribute_transform_helpers import (
    join_text_value,
    parse_integer_value,
    scan_enum_token,
)


def test_parse_integer_value_supports_supplier_seat_tokens():
    assert parse_integer_value("3 Seat") == 3
    assert parse_integer_value("4") == 4
    assert parse_integer_value("not-a-number") is None


def test_join_text_value_joins_bullets():
    assert join_text_value(["First", "Second"]) == "First\nSecond"
    assert join_text_value("Already text") == "Already text"
    assert join_text_value([]) is None


def test_scan_enum_token_matches_keywords_in_title():
    candidates = [
        "convertible",
        "sectional",
        "sleeper",
        "standard",
        "sofa_bed",
    ]
    assert (
        scan_enum_token(
            "Compression Sponge Sofa Blue Curved Modular Sectional Sleeper Couch",
            candidates,
        )
        == "sectional"
    )
    assert scan_enum_token("Boneless L-Shape Sectional Sofa", candidates) == "sectional"
    assert scan_enum_token("Plain couch", candidates) is None
