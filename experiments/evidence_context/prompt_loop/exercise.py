"""Optional learner exercise; never imported by the frozen experiment."""


def eligible_for_review(
    baseline_passes: int, candidate_passes: int, citation_failures: int
) -> bool:
    """Decide whether a candidate earns independent review, not deployment.

    TODO: Write 5-10 lines defining your policy. Consider whether a single citation
    failure should veto an improved aggregate score, and whether a tie warrants
    more review. Document why. Inputs are nonnegative counts from equal-size runs.
    No implementation here changes Stage 7's preserved winner.
    """
    raise NotImplementedError("Learner policy exercise")
