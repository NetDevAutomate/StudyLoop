"""Start the real StudyLoop CLI with a test-only content generator injected."""

from __future__ import annotations

import os

from _content_generator import DeterministicTestGenerator, GeneratorFixtureConfig

import studyloop.content.job as job_module


def _test_generator(_config: object) -> DeterministicTestGenerator:
    count = int(os.environ.get("STUDYLOOP_TEST_CARD_COUNT", "3"))
    return DeterministicTestGenerator(GeneratorFixtureConfig(card_count=count))


job_module.get_generator = _test_generator

from studyloop.cli import cli  # noqa: E402

if __name__ == "__main__":
    cli()
