"""Prompts used by ``dictation-bench corpus record``.

Prompts are short by design.  A person reading twelve long paragraphs aloud
stops recording; twelve sentences take two minutes and produce a corpus that is
actually finished.  The wording mirrors the phrases someone really dictates
(commands, names, numbers) rather than literary prose, because that is where
engines disagree.

Ids are stable: ``--prompt m03`` selects the same sentence forever, so a corpus
can be re-recorded later and compared clip by clip.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PromptError


@dataclass(frozen=True)
class Prompt:
    id: str
    group: str
    text: str


PROMPTS: tuple[Prompt, ...] = (
    # Everyday dictation prose: short, first-person, what people actually say.
    Prompt("m01", "main", "Let's sync on the release plan after lunch."),
    Prompt("m02", "main", "Can you move that meeting to Thursday afternoon?"),
    Prompt("m03", "main", "I'll review the pull request once the tests pass."),
    Prompt("m04", "main", "Send the summary to the team and cc me."),
    Prompt("m05", "main", "Remind me to renew the domain before it expires."),
    Prompt("m06", "main", "The build failed again on the same integration test."),
    Prompt("m07", "main", "Draft a short reply saying I'll get back to them Monday."),
    Prompt("m08", "main", "Add a note to the ticket that the fix is in review."),
    Prompt("m09", "main", "I think the second paragraph reads better without the list."),
    Prompt("m10", "main", "Let's hold off on the migration until next week."),
    Prompt("m11", "main", "Please tidy up the error message; it's too vague."),
    Prompt("m12", "main", "Book a room for the retro on Friday at three."),
    # Proper nouns and product names: the usual real-world failures.
    Prompt("j01", "jargon", "Restart the WhisperKit server and try again."),
    Prompt("j02", "jargon", "Deploy the Rust service to the Frankfurt cluster."),
    Prompt("j03", "jargon", "Ask Priya to update the Kubernetes manifest."),
    Prompt("j04", "jargon", "Push the transcript to Notion and link the Linear issue."),
    Prompt("j05", "jargon", "Run the benchmark against Parakeet and Nemotron."),
    Prompt("j06", "jargon", "Check the Grafana dashboard for the queue latency."),
    Prompt("j07", "jargon", "Ping the Copenhagen office about the timezone shift."),
    Prompt("j08", "jargon", "Use PostgreSQL for the audit table, not SQLite."),
    # Numbers, times, money: where formats diverge most.
    Prompt("n01", "numeric", "The invoice total is one thousand two hundred and fifty dollars."),
    Prompt("n02", "numeric", "Call me back at four forty-five on extension two three one."),
    Prompt("n03", "numeric", "We shipped version two point fourteen on the third of March."),
    Prompt("n04", "numeric", "Set the retry limit to five and the timeout to thirty seconds."),
    Prompt("n05", "numeric", "Move ninety megabytes of logs to the cold bucket."),
    Prompt("n06", "numeric", "The order number is six eight two four and it arrives Tuesday."),
    # Acronyms and spelled-out letters: the stress cases.
    Prompt("s01", "stress", "Open the README in VSCode and search for API rate limits."),
    Prompt("s02", "stress", "Run git rebase dash dash interactive on the feature branch."),
    Prompt("s03", "stress", "The F nineteen key toggles the speech to text overlay."),
    Prompt("s04", "stress", "Export the CSV and upload it to the S3 bucket."),
    # One long utterance: how cost and accuracy behave on realistic dictation.
    Prompt("L01", "long", "I want to add a keyboard shortcut that starts a local speech "
                          "to text server, keeps the model resident in memory, and pastes "
                          "the result into whichever app has focus, without sending any "
                          "audio off the machine."),
    Prompt("L02", "long", "Before we merge, please check that the new migration runs on "
                          "SQLite and PostgreSQL, that the rollback path still works, and "
                          "that the changelog mentions the behaviour change."),
)


def all_prompts(groups: list[str] | None = None) -> list[Prompt]:
    """Prompts in bank order, optionally limited to ``groups``."""
    if not groups:
        return list(PROMPTS)
    wanted = {g.strip().lower() for g in groups if g.strip()}
    known = {p.group for p in PROMPTS}
    unknown = sorted(wanted - known)
    if unknown:
        raise PromptError(
            f"unknown prompt group(s): {', '.join(unknown)}; "
            f"choose from {', '.join(sorted(known))}"
        )
    return [p for p in PROMPTS if p.group in wanted]


def grouped(groups: list[str] | None = None) -> dict[str, list[Prompt]]:
    """Prompts bucketed by group, in first-seen order."""
    buckets: dict[str, list[Prompt]] = {}
    for prompt in all_prompts(groups):
        buckets.setdefault(prompt.group, []).append(prompt)
    return buckets
