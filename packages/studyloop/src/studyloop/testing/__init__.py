"""Test-support package — shipped so the e2e harness can spawn real binaries.

Only the fake agent lives here; nothing in this package runs in normal
operation (the fake adapter registers only under STUDYLOOP_TEST_AGENT=1).
"""
