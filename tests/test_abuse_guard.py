import uuid

import pytest

from app.config import Settings
from app.domain.errors import RateLimitError, ValidationError
from app.services.abuse_guard import InMemoryAbuseGuard, check_honeypot


def test_honeypot_rejects_filled_field():
    with pytest.raises(ValidationError):
        check_honeypot("spam@bot.com")


def test_honeypot_allows_empty():
    check_honeypot(None)
    check_honeypot("")
    check_honeypot("  ")


def test_in_memory_guest_and_ip_limits():
    settings = Settings(
        rate_limit_per_hour=2,
        rate_limit_per_ip_per_hour=3,
        rate_limit_min_interval_seconds=0,
    )
    guard = InMemoryAbuseGuard(settings)
    guest = uuid.uuid4()
    ip = "203.0.113.1"

    guard.check(guest, ip)
    guard.check(guest, ip)
    with pytest.raises(RateLimitError, match="Rate limit exceeded"):
        guard.check(guest, ip)


def test_in_memory_cooldown():
    settings = Settings(
        rate_limit_per_hour=10,
        rate_limit_per_ip_per_hour=10,
        rate_limit_min_interval_seconds=3600,
    )
    guard = InMemoryAbuseGuard(settings)
    guest = uuid.uuid4()
    ip = "203.0.113.2"

    guard.check(guest, ip)
    with pytest.raises(RateLimitError, match="wait a few minutes"):
        guard.check(guest, ip)
