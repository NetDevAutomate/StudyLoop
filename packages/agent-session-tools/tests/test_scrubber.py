# pragma: allowlist-file
"""Tests for the scrubber module — secrets detection and redaction."""

from __future__ import annotations


from agent_session_tools.scrubber import (
    SECRET_PATTERNS,
    ScrubReport,
    ScrubResult,
    Scrubber,
    create_scrubber,
    load_scrub_config,
)

# ---------------------------------------------------------------------------
# Realistic but obviously fake test credentials
# All values are from official documentation examples or clearly synthetic.
# ---------------------------------------------------------------------------

AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
AWS_SECRET_KEY_VALUE = (
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
)
AWS_SECRET_KEY_TEXT = "aws secret_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"  # pragma: allowlist secret
GITHUB_PAT = "ghp_" + "A" * 36
GITHUB_FINE_GRAINED = "github_pat_" + "B" * 82
GITHUB_OAUTH = "gho_" + "C" * 36
OPENAI_KEY = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"  # pragma: allowlist secret
ANTHROPIC_KEY = "sk-ant-" + "D" * 88  # pragma: allowlist secret
JWT_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"  # pragma: allowlist secret
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
# Constructed at runtime to avoid detect-private-key hook literal match
PRIVATE_KEY_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"
CONNECTION_STRING = (
    "postgres://myuser:mysecretpassword@localhost:5432/mydb"  # pragma: allowlist secret
)
GCP_API_KEY = "AIza" + "E" * 35  # pragma: allowlist secret
STRIPE_TEST_KEY = "sk_test_" + "F" * 24  # pragma: allowlist secret
_SLACK_SUFFIX = "-12345678901-12345678901-ABCDEFGHIJKLMNOP"  # pragma: allowlist secret
SLACK_BOT_TOKEN = "xoxb" + _SLACK_SUFFIX  # pragma: allowlist secret
GENERIC_SECRET = "password = 'supersecret123'"  # pragma: allowlist secret


# ===========================================================================
# SECRET_PATTERNS — individual pattern coverage
# ===========================================================================


class TestSecretPatterns:
    """Each pattern must match its canonical example."""

    def test_aws_access_key(self):
        assert SECRET_PATTERNS["aws_access_key"].search(AWS_ACCESS_KEY)

    def test_aws_access_key_no_false_positive(self):
        assert not SECRET_PATTERNS["aws_access_key"].search("NOTANAWSKEY12345678901")

    def test_aws_secret_key(self):
        assert SECRET_PATTERNS["aws_secret_key"].search(AWS_SECRET_KEY_TEXT)

    def test_github_pat(self):
        assert SECRET_PATTERNS["github_pat"].search(GITHUB_PAT)

    def test_github_fine_grained(self):
        assert SECRET_PATTERNS["github_fine_grained"].search(GITHUB_FINE_GRAINED)

    def test_github_oauth(self):
        assert SECRET_PATTERNS["github_oauth"].search(GITHUB_OAUTH)

    def test_openai_key(self):
        assert SECRET_PATTERNS["openai_key"].search(OPENAI_KEY)

    def test_anthropic_key(self):
        assert SECRET_PATTERNS["anthropic_key"].search(ANTHROPIC_KEY)

    def test_jwt(self):
        assert SECRET_PATTERNS["jwt"].search(JWT_TOKEN)

    def test_private_key_header(self):
        assert SECRET_PATTERNS["private_key_header"].search(PRIVATE_KEY_HEADER)

    def test_private_key_header_ec_variant(self):
        assert SECRET_PATTERNS["private_key_header"].search(
            "-----BEGIN EC " + "PRIVATE KEY-----"  # pragma: allowlist secret
        )

    def test_connection_string_postgres(self):
        assert SECRET_PATTERNS["connection_string"].search(CONNECTION_STRING)

    def test_connection_string_mysql(self):
        assert SECRET_PATTERNS["connection_string"].search(
            "mysql://root:password123@db.example.com/mydb"  # pragma: allowlist secret
        )

    def test_connection_string_mongodb(self):
        assert SECRET_PATTERNS[
            "connection_string"
        ].search(
            "mongodb://admin:secretpass@mongo.host:27017/authdb"  # pragma: allowlist secret
        )

    def test_connection_string_redis(self):
        assert SECRET_PATTERNS["connection_string"].search(
            "redis://default:redispass@redis.host:6379"  # pragma: allowlist secret
        )

    def test_gcp_api_key(self):
        assert SECRET_PATTERNS["gcp_api_key"].search(GCP_API_KEY)

    def test_stripe_test_key(self):
        assert SECRET_PATTERNS["stripe_key"].search(STRIPE_TEST_KEY)

    def test_stripe_live_key(self):
        assert SECRET_PATTERNS["stripe_key"].search("sk_live_" + "G" * 24)

    def test_slack_bot_token(self):
        assert SECRET_PATTERNS["slack_bot_token"].search(SLACK_BOT_TOKEN)

    def test_generic_secret_password(self):
        assert SECRET_PATTERNS["generic_secret"].search(GENERIC_SECRET)

    def test_generic_secret_api_key(self):
        assert SECRET_PATTERNS["generic_secret"].search(
            "api_key = 'abc123defgh'"  # pragma: allowlist secret
        )

    def test_generic_secret_too_short_not_matched(self):
        # Values shorter than 8 chars should not match
        assert not SECRET_PATTERNS["generic_secret"].search("token = 'abc'")

    def test_pattern_count(self):
        """Ensure we have exactly 14 named patterns (no silent additions/removals)."""
        assert len(SECRET_PATTERNS) == 14


# ===========================================================================
# ScrubResult
# ===========================================================================


class TestScrubResult:
    def test_scrubbed_true_when_findings_present(self):
        result = ScrubResult(text="redacted", findings=[{"type": "aws_access_key"}])
        assert result.scrubbed is True

    def test_scrubbed_false_when_no_findings(self):
        result = ScrubResult(text="clean text", findings=[])
        assert result.scrubbed is False

    def test_scrubbed_false_on_default(self):
        result = ScrubResult(text="hello")
        assert result.scrubbed is False


# ===========================================================================
# ScrubReport
# ===========================================================================


class TestScrubReport:
    def test_add_increments_messages_scanned(self):
        report = ScrubReport()
        report.add(ScrubResult(text="clean"))
        report.add(ScrubResult(text="also clean"))
        assert report.messages_scanned == 2

    def test_add_only_counts_dirty_messages(self):
        report = ScrubReport()
        report.add(ScrubResult(text="clean"))
        report.add(ScrubResult(text="dirty", findings=[{"type": "aws_access_key"}]))
        assert report.messages_with_secrets == 1

    def test_add_accumulates_total_findings(self):
        report = ScrubReport()
        report.add(
            ScrubResult(
                text="x",
                findings=[{"type": "aws_access_key"}, {"type": "github_pat"}],
            )
        )
        report.add(
            ScrubResult(
                text="y",
                findings=[{"type": "aws_access_key"}],
            )
        )
        assert report.total_findings == 3

    def test_add_aggregates_findings_by_type(self):
        report = ScrubReport()
        report.add(
            ScrubResult(
                text="x",
                findings=[{"type": "aws_access_key"}, {"type": "github_pat"}],
            )
        )
        report.add(
            ScrubResult(
                text="y",
                findings=[{"type": "aws_access_key"}],
            )
        )
        assert report.findings_by_type["aws_access_key"] == 2
        assert report.findings_by_type["github_pat"] == 1

    def test_add_clean_result_leaves_counts_zero(self):
        report = ScrubReport()
        report.add(ScrubResult(text="nothing here"))
        assert report.messages_with_secrets == 0
        assert report.total_findings == 0
        assert report.findings_by_type == {}


# ===========================================================================
# Scrubber
# ===========================================================================


class TestScrubberEdgeCases:
    def test_empty_string_returns_empty(self):
        s = Scrubber()
        result = s.scrub("")
        assert result.text == ""
        assert result.findings == []

    def test_none_equivalent_falsy_input(self):
        # The implementation guards `if not text` — None would hit this too,
        # but the type hint is str. Test the empty-string path explicitly.
        s = Scrubber()
        result = s.scrub("")
        assert not result.scrubbed

    def test_clean_text_unchanged(self):
        s = Scrubber()
        text = "This is a perfectly clean message with no secrets."
        result = s.scrub(text)
        assert result.text == text
        assert result.scrubbed is False


class TestScrubberDetection:
    def test_aws_access_key_is_replaced(self):
        s = Scrubber()
        result = s.scrub(f"Key is {AWS_ACCESS_KEY} use it")
        assert AWS_ACCESS_KEY not in result.text
        assert result.scrubbed is True

    def test_github_pat_is_replaced(self):
        s = Scrubber()
        result = s.scrub(f"token={GITHUB_PAT}")
        assert GITHUB_PAT not in result.text

    def test_connection_string_is_replaced(self):
        s = Scrubber()
        result = s.scrub(f"Connect via {CONNECTION_STRING}")
        assert "mysecretpassword" not in result.text

    def test_finding_contains_type_and_placeholder(self):
        s = Scrubber()
        result = s.scrub(AWS_ACCESS_KEY)
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding["type"] == "aws_access_key"
        assert "placeholder" in finding
        assert "length" in finding

    def test_finding_does_not_contain_original_value(self):
        s = Scrubber()
        result = s.scrub(AWS_ACCESS_KEY)
        for finding in result.findings:
            assert AWS_ACCESS_KEY not in str(finding)


class TestScrubberDeterministicPlaceholders:
    def test_same_secret_same_placeholder(self):
        s = Scrubber()
        result1 = s.scrub(f"First mention: {AWS_ACCESS_KEY}")
        result2 = s.scrub(f"Second mention: {AWS_ACCESS_KEY}")
        placeholder1 = result1.findings[0]["placeholder"]
        placeholder2 = result2.findings[0]["placeholder"]
        assert placeholder1 == placeholder2

    def test_different_secrets_different_placeholders(self):
        s = Scrubber()
        result1 = s.scrub(GITHUB_PAT)
        result2 = s.scrub(GITHUB_OAUTH)
        p1 = result1.findings[0]["placeholder"]
        p2 = result2.findings[0]["placeholder"]
        assert p1 != p2

    def test_placeholder_format(self):
        s = Scrubber()
        result = s.scrub(AWS_ACCESS_KEY)
        placeholder = result.findings[0]["placeholder"]
        # Must match [TYPE-NNN] pattern
        assert placeholder.startswith("[AWS_ACCESS_KEY-")
        assert placeholder.endswith("]")

    def test_counter_increments_per_type(self):
        s = Scrubber()
        key1 = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
        key2 = "AKIAIOSFODNN7EXAMPL2"  # pragma: allowlist secret
        s.scrub(key1)
        result2 = s.scrub(key2)
        placeholder2 = result2.findings[0]["placeholder"]
        assert placeholder2 == "[AWS_ACCESS_KEY-002]"


class TestScrubberAllowlistValues:
    def test_allowlisted_value_not_scrubbed(self):
        s = Scrubber(allowlist_values=[AWS_ACCESS_KEY])
        result = s.scrub(f"key={AWS_ACCESS_KEY}")
        assert AWS_ACCESS_KEY in result.text
        assert result.scrubbed is False

    def test_non_allowlisted_value_still_scrubbed(self):
        other_key = "AKIAIOSFODNN7EXAMPL3"  # pragma: allowlist secret
        s = Scrubber(allowlist_values=[AWS_ACCESS_KEY])
        result = s.scrub(other_key)
        assert other_key not in result.text
        assert result.scrubbed is True

    def test_empty_allowlist_values_scrubs_normally(self):
        s = Scrubber(allowlist_values=[])
        result = s.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is True


class TestScrubberAllowlistPatterns:
    def test_allowlist_pattern_prevents_scrub(self):
        # Allow anything that looks like our synthetic test keys
        s = Scrubber(allowlist_patterns=[AWS_ACCESS_KEY])
        result = s.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is False

    def test_allowlist_pattern_partial_match(self):
        # Pattern matches a substring of the secret value
        s = Scrubber(allowlist_patterns=[r"EXAMPLE$"])
        result = s.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is False

    def test_non_matching_pattern_still_scrubs(self):
        s = Scrubber(allowlist_patterns=[r"NOMATCH_PATTERN"])
        result = s.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is True


# ===========================================================================
# Scrubber.scrub_sql
# ===========================================================================


class TestScrubberScrubSql:
    def test_scrub_sql_clean_returns_unchanged_sql(self):
        s = Scrubber()
        sql = "SELECT id, content FROM messages WHERE id = 1;"
        scrubbed_sql, report = s.scrub_sql(sql)
        assert scrubbed_sql == sql
        assert report.messages_scanned == 1
        assert report.messages_with_secrets == 0
        assert report.total_findings == 0

    def test_scrub_sql_dirty_replaces_secret(self):
        s = Scrubber()
        sql = f"INSERT INTO messages VALUES ('msg1', 'Key: {AWS_ACCESS_KEY}');"
        scrubbed_sql, report = s.scrub_sql(sql)
        assert AWS_ACCESS_KEY not in scrubbed_sql
        assert report.messages_scanned == 1
        assert report.messages_with_secrets == 1
        assert report.total_findings >= 1

    def test_scrub_sql_report_findings_by_type(self):
        s = Scrubber()
        sql = f"INSERT INTO t VALUES ('{AWS_ACCESS_KEY}');"
        _, report = s.scrub_sql(sql)
        assert "aws_access_key" in report.findings_by_type

    def test_scrub_sql_returns_tuple(self):
        s = Scrubber()
        result = s.scrub_sql("SELECT 1;")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ===========================================================================
# Scrubber.stats
# ===========================================================================


class TestScrubberStats:
    def test_stats_empty_on_init(self):
        s = Scrubber()
        assert s.stats == {}

    def test_stats_tracks_scrubbed_types(self):
        s = Scrubber()
        s.scrub(AWS_ACCESS_KEY)
        assert s.stats.get("aws_access_key") == 1

    def test_stats_increments_across_scrub_calls(self):
        s = Scrubber()
        s.scrub(GITHUB_PAT)
        s.scrub(GITHUB_OAUTH)
        # Both are different types (github_pat vs github_oauth)
        assert s.stats.get("github_pat") == 1
        assert s.stats.get("github_oauth") == 1

    def test_stats_does_not_double_count_same_value(self):
        # Same secret scrubbed twice → placeholder reused, counter stays at 1
        s = Scrubber()
        s.scrub(AWS_ACCESS_KEY)
        s.scrub(AWS_ACCESS_KEY)
        assert s.stats.get("aws_access_key") == 1

    def test_stats_returns_copy(self):
        s = Scrubber()
        s.scrub(AWS_ACCESS_KEY)
        stats = s.stats
        stats["injected"] = 99
        assert "injected" not in s.stats


# ===========================================================================
# load_scrub_config
# ===========================================================================


class TestLoadScrubConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        config = load_scrub_config(tmp_path)
        assert config == {"allowlist": {"patterns": [], "values": []}}

    def test_existing_toml_is_parsed(self, tmp_path):
        toml_content = (
            f'[allowlist]\npatterns = ["EXAMPLE"]\nvalues = ["{AWS_ACCESS_KEY}"]\n'
        )
        (tmp_path / "scrub-config.toml").write_text(toml_content)
        config = load_scrub_config(tmp_path)
        assert config["allowlist"]["patterns"] == ["EXAMPLE"]
        assert config["allowlist"]["values"] == [AWS_ACCESS_KEY]

    def test_empty_toml_returns_empty_dict(self, tmp_path):
        (tmp_path / "scrub-config.toml").write_bytes(b"")
        config = load_scrub_config(tmp_path)
        # tomllib parses empty file as {}
        assert isinstance(config, dict)


# ===========================================================================
# create_scrubber
# ===========================================================================


class TestCreateScrubber:
    def test_returns_scrubber_instance(self, tmp_path):
        scrubber = create_scrubber(tmp_path)
        assert isinstance(scrubber, Scrubber)

    def test_no_config_dir_returns_default_scrubber(self, tmp_path):
        # Scrubber from missing config should behave normally (no allowlists)
        scrubber = create_scrubber(tmp_path)
        result = scrubber.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is True

    def test_config_dir_with_allowlist_values_honoured(self, tmp_path):
        toml_content = f'[allowlist]\nvalues = ["{AWS_ACCESS_KEY}"]\n'
        (tmp_path / "scrub-config.toml").write_text(toml_content)
        scrubber = create_scrubber(tmp_path)
        result = scrubber.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is False

    def test_config_dir_with_allowlist_patterns_honoured(self, tmp_path):
        toml_content = f'[allowlist]\npatterns = ["{AWS_ACCESS_KEY}"]\n'
        (tmp_path / "scrub-config.toml").write_text(toml_content)
        scrubber = create_scrubber(tmp_path)
        result = scrubber.scrub(AWS_ACCESS_KEY)
        assert result.scrubbed is False
