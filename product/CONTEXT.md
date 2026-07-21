# Career CoDesk Provenance Domain

The synthetic Career CoDesk prototype records learner-support evidence without treating AI output
or restricted safety handling as ordinary career facts.

## Language

**Learner**:
A synthetic fixture identity, distinct from a course enrolment and an operational case.
_Avoid_: Case, enrolment

**Need capture**:
An append-only, source-qualified statement about a learner need; a correction is a new capture that
links to the statement it supersedes.
_Avoid_: Editable learner profile, final assessment

**Need hypothesis**:
A provisional AI interpretation that cites exact need captures and has no decision authority.
_Avoid_: Fact, diagnosis

**Support decision**:
An immutable adviser-owned approve, amend, or reject event over a proposed intervention allocation.
_Avoid_: AI decision, automatic approval

**Safety exit**:
A restricted human-handling record that removes a case from the ordinary workflow and carries no
score or score-like metadata. It may contain only one qualitative signal and is not reachable
from an ordinary need capture.
_Avoid_: Career barrier, risk score

**Outcome confirmation**:
An append-only response about one delivery event. An unresolved outcome may cause exactly one
automated reopening transition for that delivery event's case.
_Avoid_: A direct case-reopen command, mutable case status
