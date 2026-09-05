"""Optional learner experiment, deliberately disconnected from the frozen policy."""


def classify_revision(recorded: str | None, target: str) -> str:
    """Return match, mismatch or unknown for one revision field.

    TODO: Write 5-10 lines and explain your equality policy. Should r2 and R2
    denote the same revision? Missing recorded metadata must remain unknown.
    Do not infer the recorded revision from target, or assume revision compatibility.
    Compare your decision with policy.py's deliberately strict equality rule.
    This exercise never changes the preserved Stage 8 run.
    """
    raise NotImplementedError("Optional learner revision-policy exercise")
