"""Opt-in linear terminal presentation; no accessibility conformance claim."""
import unicodedata
import re
from .pilot_review import terminal, display_task

DECISIONS = {
    'ACCEPT_EVIDENCE': 'Accept evidence for this narrow claim only',
    'REJECT_EVIDENCE': 'Reject evidence for this narrow claim only',
    'NEEDS_MORE_EVIDENCE': 'Needs more evidence; uncertainty remains',
    'NOT_APPLICABLE': 'Not applicable to this claim',
    'ESCALATE_FOR_REVIEW': 'Escalate conflicting or unresolved evidence for review',
}


def safe_text(value):
    # Leave line breaks to the output function: untrusted content cannot move the
    # cursor, change direction, ring a bell, clear a screen or forge a new line.
    return ''.join(('\\u%04x' % ord(c)) if unicodedata.category(c).startswith('C')
                   or c in ('\u2028', '\u2029') else c for c in str(value))


def plain_output(output):
    def emit(value):
        text = safe_text(value)
        for code, label in DECISIONS.items():
            if re.fullmatch(r'[1-5]\. ' + re.escape(code), text):
                text = text[:-len(code)] + label
        output(text)
    return emit


def show_task(task, position, total, output=print, source_root=None):
    emit = plain_output(output)
    emit('Evidence may be lengthy. Read source fields separately from automated interpretations; unknown proof stays unknown.')
    emit('Read-only evidence review. Use numbered choices and Enter. No color or mouse is required.')
    display_task(task, position, total, emit, source_root)
    emit('Unknown means proof is missing. Accepting evidence does not fill a missing proof obligation.')


def accessible_terminal(store, session_id, resume_key, *, input_fn=input, output=print):
    from .pilot_session_store import read_session
    from .pilot_session_models import MeasurementKind
    from .evidence_io import EvidenceError
    session, _, _ = read_session(store, session_id, resume_key)
    if session.protocol.measurement_kind is not MeasurementKind.SIMULATED:
        raise EvidenceError('C6_adapter_supports_simulated_sessions_only')
    emit = plain_output(output)
    emit('Timing is optional: choose No to timing and continue untimed. Declining timing does not decline the study.')
    emit('Observation is a saved source field. An automated assessment is an interpretation, not additional evidence.')
    emit('Keyboard instructions: enter a numbered choice and press Enter. Enter q to save and stop, or w to withdraw.')
    emit('The same task is presented again after a pause. Invalid input can be corrected without losing saved responses.')
    return terminal(store, session_id, resume_key, input_fn=input_fn, output=emit)


def audit():
    return {'scope': 'AUTOMATED_SOFTWARE_AUDIT_NOT_INDEPENDENT_USER_EVALUATION',
        'keyboard_only': 'IMPLEMENTED_numbered_choices_enter_q_w',
        'focus_and_order': 'LINEAR_no_cursor_repositioning_or_dynamic_focus',
        'labels': 'PLAIN_LANGUAGE_evidence_decisions_and_explicit_scope',
        'color_only_cues': False, 'control_characters': 'ESCAPED_IN_OPT_IN_ADAPTER',
        'error_recovery': 'INVALID_INPUT_REPROMPT_saved_responses_preserved',
        'screen_reader_compatibility': 'UNKNOWN_requires_real_assistive_technology_evaluation',
        'standards_conformance': 'NOT_EVALUATED', 'actual_human_usability': 'UNKNOWN',
        'limitations': ['Long evidence listings and JSON field labels may be burdensome.',
            'Terminal and assistive-technology combinations have not been evaluated.',
            'Closed choices limit nuanced explanations; source paths may reveal control names.']}
