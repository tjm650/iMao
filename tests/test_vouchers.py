from backend.app.vouchers import generate_voucher_code, normalize_code


def test_voucher_codes_are_grouped_and_uppercase():
    code = generate_voucher_code()
    assert len(code) == 19
    assert code == code.upper()
    assert len(code.split("-")) == 4


def test_normalize_voucher_code():
    assert normalize_code(" abcd-1234 efgh ") == "ABCD-1234EFGH"
