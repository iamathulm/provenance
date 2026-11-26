import uuid

from provenance.storage.signing import sign, verify

SECRET = "s" * 48
FILE_ID, WORKSPACE_ID, USER_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_round_trip_within_ttl() -> None:
    link = sign(FILE_ID, WORKSPACE_ID, USER_ID, SECRET, ttl_s=300, now=1_000)

    assert link.expires == 1_300
    assert verify(FILE_ID, WORKSPACE_ID, USER_ID, link.expires, link.signature, SECRET, now=1_299)


def test_rejects_expired_link() -> None:
    link = sign(FILE_ID, WORKSPACE_ID, USER_ID, SECRET, ttl_s=300, now=1_000)

    assert not verify(
        FILE_ID, WORKSPACE_ID, USER_ID, link.expires, link.signature, SECRET, now=1_301
    )


def test_rejects_tampered_signature_or_expiry() -> None:
    link = sign(FILE_ID, WORKSPACE_ID, USER_ID, SECRET, now=1_000)
    flipped = ("0" if link.signature[0] != "0" else "1") + link.signature[1:]

    assert not verify(FILE_ID, WORKSPACE_ID, USER_ID, link.expires, flipped, SECRET, now=1_000)
    assert not verify(
        FILE_ID, WORKSPACE_ID, USER_ID, link.expires + 3600, link.signature, SECRET, now=1_000
    )


def test_rejects_other_user_file_workspace_or_secret() -> None:
    link = sign(FILE_ID, WORKSPACE_ID, USER_ID, SECRET, now=1_000)
    other = uuid.uuid4()

    assert not verify(FILE_ID, WORKSPACE_ID, other, link.expires, link.signature, SECRET, now=1_000)
    assert not verify(other, WORKSPACE_ID, USER_ID, link.expires, link.signature, SECRET, now=1_000)
    assert not verify(FILE_ID, other, USER_ID, link.expires, link.signature, SECRET, now=1_000)
    assert not verify(
        FILE_ID, WORKSPACE_ID, USER_ID, link.expires, link.signature, "x" * 48, now=1_000
    )
