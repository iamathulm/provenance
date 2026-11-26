from provenance.auth.passwords import hash_password, verify_password


def test_hash_round_trip() -> None:
    hashed = hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")


def test_wrong_password_rejected() -> None:
    assert not verify_password(hash_password("correct horse battery"), "wrong horse battery")


def test_malformed_hash_rejected() -> None:
    assert not verify_password("not-a-hash", "anything")
