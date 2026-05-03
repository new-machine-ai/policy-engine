from multi_agent_drift import DriftDetector, DriftType


def test_drift_detector_finds_config_policy_trust_capability_and_version_drift():
    detector = DriftDetector()
    sources = [
        {
            "label": "source",
            "config": {
                "isolation": "serializable",
                "require_human_approval": True,
                "max_tool_calls": 10,
            },
            "policies": {
                "trade": {"market_hours_only": True},
                "pii": {"redact": True},
            },
            "trust_scores": {"planner": 0.95},
            "trust_tolerance": 0.1,
            "capabilities": {"planner": ["search"]},
            "components": {"svc/a": "2.0.0", "svc/b": "2.0.0"},
        },
        {
            "label": "target",
            "config": {
                "isolation": "read_committed",
                "max_tool_calls": 25,
            },
            "policies": {
                "trade": {"market_hours_only": False},
            },
            "trust_scores": {"planner": 0.5},
            "trust_tolerance": 0.1,
            "capabilities": {"planner": ["search", "exec_code"]},
            "components": {"svc/c": "1.9.0"},
        },
    ]

    report = detector.scan(sources)
    types = {finding.drift_type for finding in report.findings}

    assert DriftType.CONFIG_DRIFT in types
    assert DriftType.POLICY_DRIFT in types
    assert DriftType.TRUST_DRIFT in types
    assert DriftType.CAPABILITY_DRIFT in types
    assert DriftType.VERSION_DRIFT in types
    assert any(finding.severity == "critical" for finding in report.findings)
    assert "finding(s)" in report.summary

    markdown = detector.to_markdown(report)
    assert "# Drift Detection Report" in markdown
    assert "capability_drift" in markdown


def test_drift_detector_returns_empty_report_for_matching_sources():
    detector = DriftDetector()
    sources = [
        {"label": "a", "config": {"mode": "safe"}, "components": {"svc/a": "1.0.0"}},
        {"label": "b", "config": {"mode": "safe"}, "components": {"svc/b": "1.0.0"}},
    ]

    report = detector.scan(sources)

    assert report.findings == []
    assert report.summary == "0 finding(s): 0 critical, 0 warning, 0 info"
