import random

_ZINGERS: dict[str, list[str]] = {
    "purdue": [
        "That's a bold strategy, {user} — betting on Purdue.",
        "{user} really said \"trust the Boilermakers\" with their whole chest.",
        "Boiler up, {user}? We'll see about that.",
        "{user} out here believing in Purdue football. Respect the courage.",
        "Riding with the Boilermakers, {user}? Living dangerously.",
    ],
    "ohio state": [
        "{user} taking the safe chalk with Ohio State - groundbreaking stuff.",
        "Betting on Ohio State, {user}? Truly a shocking, unprecedented take.",
        "{user} really needed a bet to tell us Ohio State is good.",
        "The Buckeyes - {user}'s daring, against-all-odds pick.",
        "{user} playing it extremely safe with the Buckeyes today.",
    ],
    "indiana": [
        "{user} betting on Indiana football? Bold. Historically bold.",
        "Indiana, {user}? Living dangerously.",
        "{user} out here trusting the Hoosiers with real (fake) money.",
        "That's one way to lose fake money, {user} - Indiana football.",
        "{user} really believes in Indiana. Someone check on them.",
    ],
    "ucf": [
        "{user} remembering UCF still claims that 2017 national title, I see.",
        "UCF, {user}? Knights of the Round Table energy.",
        "{user} betting UCF like it's still the Scott Frost era.",
        "The Knights ride again, courtesy of {user}.",
        "{user} out here representing the Group of 5 with UCF.",
    ],
}
_ZINGERS["central florida"] = _ZINGERS["ucf"]


def get_zinger(team: str | None, username: str, choice_fn=random.choice) -> str | None:
    """A one-liner for a team someone just bet on, or None if that team has no
    jokes on file. choice_fn is injectable so tests can pick deterministically
    instead of actually randomizing."""
    if team is None:
        return None
    options = _ZINGERS.get(team.strip().lower())
    if not options:
        return None
    return choice_fn(options).format(user=username)
