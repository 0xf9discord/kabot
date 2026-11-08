import asyncio

import pytest

pytest.importorskip("bson")
pytest.importorskip("cryptography")

from bson import Int64

from kabot.loco import Credentials, Endpoint, LocoPacket, PersonalClient


def test_android_profile_is_not_mixed_with_mac_fields():
    android = Credentials(123, "token", "device", "26.8.2", profile="android")
    mac = Credentials(123, "token", "device", "mac-version")
    assert android.booking_body() == {"MCCMNC": "45006", "os": "android", "userId": Int64(123)}
    assert "model" not in android.booking_body()
    assert "countryISO" not in android.checkin_body() and "useSub" not in android.checkin_body()
    assert android.login_body()["bg"] is True
    assert "dtype" not in android.login_body()
    assert mac.login_body()["dtype"] == 2 and mac.login_body()["bg"] is False


@pytest.mark.parametrize(
    "assigned_host,expected_identity",
    [("chat.test", None), ("203.0.113.77", "kakao.com"), ("2001:db8::7", "kakao.com")],
)
def test_android_discovery_uses_advertised_port_and_tls_everywhere(
    assigned_host, expected_identity
):
    async def run():
        client = PersonalClient(Credentials(123, "token", "device", "26.8.2", profile="android"))
        calls = []

        async def oneshot(endpoint, method, body):
            calls.append((endpoint, method, body))
            if method == "GETCONF":
                return LocoPacket(
                    1, method, {"ticket": {"lsl": ["ticket.test"]}, "wifi": {"ports": [9282, 995]}}
                )
            return LocoPacket(1, method, {"host": assigned_host, "port": 443})

        client._oneshot = oneshot
        assert await client.discover() == Endpoint(
            assigned_host, 443, True, server_name=expected_identity
        )
        assert calls[0][0] == Endpoint("booking-loco.kakao.com", 443, True)
        assert calls[1][0] == Endpoint("ticket.test", 9282, True)
        assert calls[1][2]["os"] == "android"

    asyncio.run(run())
