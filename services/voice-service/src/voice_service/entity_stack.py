"""Entity stack (plan sec. 4a, contract README): recency-based pronoun
resolution so "it" / "that one" / "the 10am" resolve against whatever was
most recently mentioned, instead of CollectiveOS ever seeing a bare pronoun.

Deliberately recency-based, not NLP: push a mention whenever agent speech
names something concrete (a time, a title-cased proper noun), and resolve a
pronoun in the next user utterance against the most recent matching mention.

Integration note: `UserUtterance.entity_refs` is the only place the v1
contract carries structured entity data -- `Interrupt`/`ConfirmationResponse`
have no such field. Resolution attaches to entity_refs; it does not rewrite
`text`/`modification`, since mangling a natural transcript into
"keep meeting_id_123" is a v2 contract concern (extending Interrupt with its
own entity_refs), not something to smuggle into the frozen v1 schema.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

_TIME_MENTION = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm|o'?clock)\b", re.IGNORECASE)
_PROPER_NOUN_MENTION = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*)\b")

_PRONOUNS = re.compile(
    r"\b(it|that one|this one|them|those|that|this)\b", re.IGNORECASE
)

_STOPWORDS_AS_PROPER = {"I", "Thursday", "Friday", "Monday", "Tuesday", "Wednesday", "Saturday", "Sunday"}


@dataclass
class Mention:
    label: str
    entity_id: str


@dataclass
class EntityStack:
    """One per session. `maxlen` bounds memory for a long call; only the
    most recent mentions matter for pronoun resolution anyway."""

    maxlen: int = 20
    _mentions: deque[Mention] = field(init=False)

    def __post_init__(self) -> None:
        self._mentions = deque(maxlen=self.maxlen)

    def push(self, label: str, entity_id: str) -> None:
        self._mentions.append(Mention(label=label, entity_id=entity_id))

    def observe_agent_speech(self, text: str) -> None:
        """Extracts candidate mentions from something CollectiveOS said and
        pushes them, synthesizing a local entity_id from the label itself
        when no backend id is available (v1 contract carries prose, not
        structured entities -- see module docstring)."""
        for match in _TIME_MENTION.finditer(text):
            label = match.group(0)
            self.push(label, _synthetic_id(label))
        for label in _extract_proper_nouns(text):
            self.push(label, _synthetic_id(label))

    def resolve(self, text: str) -> dict[str, str]:
        """Returns {pronoun_span: entity_id} for every pronoun in `text`
        that has a mention to resolve against -- the most recent one
        pushed, since recency is the whole heuristic. Doesn't touch `text`
        itself; see module docstring."""
        refs: dict[str, str] = {}
        if not self._mentions:
            return refs
        most_recent = self._mentions[-1]
        for match in _PRONOUNS.finditer(text):
            refs[match.group(0)] = most_recent.entity_id
        return refs

    def snapshot(self) -> list[dict[str, str]]:
        return [{"label": m.label, "entity_id": m.entity_id} for m in self._mentions]

    def restore(self, snapshot: list[dict[str, str]]) -> None:
        self._mentions.clear()
        for item in snapshot:
            self.push(item["label"], item["entity_id"])


def _extract_proper_nouns(text: str) -> list[str]:
    """Single capitalized words at the start of a sentence are usually just
    sentence-initial common words ("Checking your calendar now.", "Found
    four subscriptions...") -- capitalization alone can't tell those apart
    from real proper nouns, so those are dropped. Multi-word Title Case
    runs ("Acme Gym") are kept regardless of position: a run that long
    being capitalized by coincidence is rare enough to not bother with."""
    labels: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for match in _PROPER_NOUN_MENTION.finditer(sentence):
            label = match.group(1)
            if label in _STOPWORDS_AS_PROPER or len(label) <= 2:
                continue
            if match.start() == 0 and " " not in label:
                continue
            labels.append(label)
    return labels


def _synthetic_id(label: str) -> str:
    return "mention_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
