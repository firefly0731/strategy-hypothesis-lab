from observer.backoff import ExponentialBackoff


def test_sequence_climbs_then_caps() -> None:
    b = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset_sec=60.0)
    assert b.next_delay() == 0.5
    assert b.next_delay() == 1.0
    assert b.next_delay() == 2.0
    assert b.next_delay() == 4.0
    assert b.next_delay() == 8.0
    assert b.next_delay() == 16.0
    assert b.next_delay() == 30.0
    assert b.next_delay() == 30.0  # capped


def test_mark_connected_does_not_reset_immediately() -> None:
    b = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset_sec=60.0)
    b.next_delay()  # bump attempt to 1
    b.next_delay()  # bump attempt to 2
    b.mark_connected(now=100.0)
    # Connection just opened — disconnect happens after 30 sec → still no reset
    assert b.next_delay(now=130.0) == 2.0  # _attempt stays at 2; delay = 0.5 * 2^2


def test_sustained_connection_resets_attempts() -> None:
    b = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset_sec=60.0)
    b.next_delay()
    b.next_delay()
    b.mark_connected(now=100.0)
    # After 60+ seconds connected, next disconnect resets sequence
    assert b.next_delay(now=170.0) == 0.5
