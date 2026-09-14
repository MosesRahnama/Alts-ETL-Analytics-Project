from alts_rag.citations import number_in_quote


def test_matching_numeral_at_a_number_boundary() -> None:
    assert number_in_quote("8.2", "net return 8.2 percent")


def test_substring_inside_a_longer_number_fails() -> None:
    assert not number_in_quote("8.2", "peer median 18.2 percent")
    assert not number_in_quote("8.2", "value 8.25 percent")
