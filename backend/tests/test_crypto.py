from app.security.crypto import decrypt_secret, encrypt_secret


def test_encrypt_roundtrip_and_ciphertext_differs():
    plain = "rtsp://user:pass@192.168.1.10:554/Streaming/Channels/101"
    a, b = encrypt_secret(plain), encrypt_secret(plain)
    assert isinstance(a, bytes)
    assert plain.encode() not in a
    assert a != b  # random IV per encryption
    assert decrypt_secret(a) == decrypt_secret(b) == plain
