"""Token usage: what the conversations of sessions, their own and their subagents', were charged.

A request sends the whole context again, so a conversation costs about its requests times its mean context. The
kinds of tokens are weighted as the API prices them, in units of one input token (the constants below); what a
subscription's limit counts is not published, the weights are the nearest known."""

from dataclasses import dataclass
from pathlib import Path

from strom_tools.sessions.transcripts import api_calls, subagent_transcripts, subagent_type

_CACHE_WRITE, _CACHE_WRITE_FOR_AN_HOUR, _CACHE_READ, _OUTPUT = 1.25, 2.0, 0.1, 5.0


@dataclass(frozen=True)
class Tokens:
    """The token usage of one conversation."""

    conversation: str
    """`session`, or the type of the subagent (`reviewer`)."""
    num_calls: int
    """Its requests to the model."""
    peak_context: int
    """The largest context a request sent, in tokens."""
    written: float
    """The weighted tokens that entered the context: uncached input and cache writes."""
    reread: float
    """The weighted tokens read from the cache: the context, sent again with each request."""
    output: float
    """The weighted tokens Claude wrote: thinking, text and tool calls."""

    @property
    def total(self) -> float:
        return self.written + self.reread + self.output


def usage(path: Path) -> list[Tokens]:
    """The token usage of the session with the transcript `path`: its own conversation, then each subagent's,
    oldest first."""
    return [_tokens("session", path), *(tokens for _, tokens in subagent_usage(path))]


def subagent_usage(path: Path) -> list[tuple[str, Tokens]]:
    """The token usage of each subagent of the session with the transcript `path`, with the name of the subagent's
    transcript (`agent-ID`), oldest first."""
    return [(subagent.stem, _tokens(subagent_type(subagent), subagent)) for subagent in subagent_transcripts(path)]


def _tokens(conversation: str, path: Path) -> Tokens:
    calls = api_calls(path)
    return Tokens(
        conversation,
        len(calls),
        max((call.context for call in calls), default=0),
        sum(
            call.input + _CACHE_WRITE * call.cache_written + _CACHE_WRITE_FOR_AN_HOUR * call.cache_written_for_an_hour
            for call in calls
        ),
        sum(_CACHE_READ * call.cache_read for call in calls),
        sum(_OUTPUT * call.output for call in calls),
    )


def context(path: Path) -> int:
    """The context of the conversation with the transcript `path` at its last request, in tokens (0 before the
    first)."""
    calls = api_calls(path)
    return calls[-1].context if calls else 0
