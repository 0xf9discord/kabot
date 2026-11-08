"""Experimental, locally tested LOCO components. Live Kakao compatibility is unverified.

Install with pip install 'kabot-python[loco]'. No account login credentials are discovered.
"""

from importlib.util import find_spec

if find_spec("bson") is None or find_spec("cryptography") is None:
    raise ImportError("Install the optional LOCO dependencies: pip install 'kabot-python[loco]'")

from .adapter import run_personal_bot
from .auth import (
    ANDROID_26_8_2,
    AndroidAuthClient,
    AndroidAuthError,
    AndroidAuthProfile,
    AndroidTokens,
    RegistrationChallenge,
    RegistrationRequired,
    RegistrationStatus,
    generate_device_uuid,
)
from .client import Credentials, Message, PersonalClient, received_messages
from .crypto import CryptoError, LocoEncryptor
from .open_profile import OpenChatProfile
from .packet import LocoPacket, PacketDecoder, PacketError
from .session import EventOverflowError, LocoSession, LocoStatusError
from .transport import Endpoint, LocoConnectionError, LocoTransport

__all__ = [
    "ANDROID_26_8_2",
    "AndroidAuthClient",
    "AndroidAuthError",
    "AndroidAuthProfile",
    "AndroidTokens",
    "RegistrationChallenge",
    "RegistrationRequired",
    "RegistrationStatus",
    "generate_device_uuid",
    "Credentials",
    "CryptoError",
    "Endpoint",
    "EventOverflowError",
    "LocoConnectionError",
    "LocoEncryptor",
    "LocoPacket",
    "LocoSession",
    "LocoStatusError",
    "LocoTransport",
    "Message",
    "OpenChatProfile",
    "PacketDecoder",
    "PacketError",
    "PersonalClient",
    "received_messages",
    "run_personal_bot",
]
