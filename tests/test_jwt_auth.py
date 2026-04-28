import jwt as pyjwt

from observer.jwt_auth import make_bithumb_jwt


def test_make_bithumb_jwt_round_trip() -> None:
    token = make_bithumb_jwt(api_key="ak123", api_secret="secret456", nonce="n-1")
    decoded = pyjwt.decode(token, "secret456", algorithms=["HS256"])
    assert decoded["access_key"] == "ak123"
    assert decoded["nonce"] == "n-1"
    # Bithumb spec: no `exp`
    assert "exp" not in decoded


def test_make_bithumb_jwt_unique_nonces_when_default() -> None:
    a = make_bithumb_jwt(api_key="k", api_secret="s")
    b = make_bithumb_jwt(api_key="k", api_secret="s")
    assert a != b  # because nonce is auto-generated unique
