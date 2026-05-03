import json

import prompt_injection.cve as cve_module
from prompt_injection import McpCveFeed, VulnerabilityRecord


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_cve_feed_parses_osv_and_caches(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):  # noqa: ANN001
        calls["count"] += 1
        return _FakeResponse(
            {
                "vulns": [
                    {
                        "id": "GHSA-1",
                        "aliases": ["CVE-2099-0002"],
                        "summary": "bad package",
                        "severity": [{"score": "9.8"}],
                        "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.0.1"}]}]}],
                        "references": [{"url": "https://example.test/advisory"}],
                        "published": "2099-01-01T00:00:00Z",
                    }
                ]
            }
        )

    monkeypatch.setattr(cve_module.urllib.request, "urlopen", fake_urlopen)
    feed = McpCveFeed()

    first = feed.check_package("mcp-server-demo", "1.0.0")
    second = feed.check_package("mcp-server-demo", "1.0.0")

    assert calls["count"] == 1
    assert first[0].cve_id == "CVE-2099-0002"
    assert first[0].severity == "CRITICAL"
    assert first[0].fixed_version == "1.0.1"
    assert second[0].cve_id == first[0].cve_id


def test_manual_advisories_and_summary(monkeypatch):
    monkeypatch.setattr(cve_module.McpCveFeed, "_query_osv", lambda self, name, version, ecosystem: [])
    feed = McpCveFeed()
    feed.add_package("demo", "1.0.0")
    feed.add_manual_advisory(
        VulnerabilityRecord(
            cve_id="CVE-2099-0003",
            package="demo",
            version="1.0.0",
            severity="HIGH",
            summary="manual advisory",
        )
    )

    records = feed.check_all()

    assert len(records) == 1
    assert records[0].source == "manual"
    assert feed.summary()["HIGH"] == 1
    assert not feed.has_critical()
    assert feed.remove_package("demo") is True
