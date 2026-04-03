"""Study history data access — split into focused modules.

All public functions are re-exported here so consumers keep using:
    from studyctl.history import start_study_session
    import studyctl.history as hist
"""

from .bridges import get_bridges, migrate_bridges_to_graph, record_bridge, update_bridge_usage
from .concepts import ConceptSummary, list_concepts, seed_concepts_from_config
from .medication import check_medication_window
from .progress import (
    get_progress_for_map,
    get_progress_summary,
    get_wins,
    last_studied,
    record_progress,
    spaced_repetition_due,
)
from .search import struggle_topics, topic_frequency
from .sessions import (
    end_study_session,
    get_energy_session_data,
    get_last_session_summary,
    get_session_notes,
    get_study_session_stats,
    start_study_session,
)
from .streaks import get_study_streaks
from .teachback import get_teachback_history, record_teachback

__all__ = [
    "ConceptSummary",
    "check_medication_window",
    "end_study_session",
    "get_bridges",
    "get_energy_session_data",
    "get_last_session_summary",
    "get_progress_for_map",
    "get_progress_summary",
    "get_session_notes",
    "get_study_session_stats",
    "get_study_streaks",
    "get_teachback_history",
    "get_wins",
    "last_studied",
    "list_concepts",
    "migrate_bridges_to_graph",
    "record_bridge",
    "record_progress",
    "record_teachback",
    "seed_concepts_from_config",
    "spaced_repetition_due",
    "start_study_session",
    "struggle_topics",
    "topic_frequency",
    "update_bridge_usage",
]
