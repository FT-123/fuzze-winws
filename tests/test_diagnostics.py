from diagnostics import classify_block, dns_looks_poisoned


def test_dns_poison_detection():
    assert dns_looks_poisoned({"203.0.113.1"}, {"198.51.100.1"})
    assert not dns_looks_poisoned({"1.1.1.1", "2.2.2.2"}, {"2.2.2.2"})
    assert not dns_looks_poisoned(set(), {"1.1.1.1"})
    assert not dns_looks_poisoned({"1.1.1.1"}, set())


def test_classify_block():
    assert classify_block(True, True, True, True, True, "unknown") == "none"
    assert classify_block(False, False, False, False, False, "full_or_partial") == "ip"
    assert classify_block(True, False, False, False, False, "unknown") == "tls12_server_hello"
    assert classify_block(True, True, False, False, False, "unknown") == "tls13"
    assert classify_block(True, True, True, False, True, "unknown") == "quic"
    assert classify_block(True, True, True, False, False, "unknown") == "none"
    assert classify_block(False, True, True, True, True, "unknown") == "http"
