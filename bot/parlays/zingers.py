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
    "oklahoma state": [
        "{user} betting on Oklahoma State? Bold - are we a 40-year-old man about this?",
        "The Cowboys, {user}? Stillwater's finest, allegedly.",
        "{user} riding with Oklahoma State. Pistol Pete would be proud.",
        "{user} out here trusting Oklahoma State with real (fake) money.",
        "Cowboys up, {user}? We'll see about that.",
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


_GENERIC_FLAIR_LINES = [
    "{user} has picked a side. Bold. Very bold.",
    "New flair just dropped for {user} - the rivalry begins.",
    "{user} is officially team-pilled.",
    "Bandwagon check: {user}, is this your real team or just this week's vibe?",
    "{user} locked in a flair. No takebacks (well, /flair clear exists, but still).",
    "{user} is now flying the flag. Hope it doesn't end in tears.",
]

_EMOJI_LETTER_WORDS = ["WOW", "LOL", "NICE", "HYPE", "GOAT", "SWAG", "VIBES", "BASED", "MOOD", "RAD"]

_REGIONAL_INDICATOR_A = 0x1F1E6


def _spell_in_emoji(word: str) -> str:
    """Spells a word out with regional-indicator letter emoji, e.g. WOW ->
    'W O W'. Joined with spaces (not concatenated directly) so consecutive
    letter pairs never accidentally read as a country flag emoji - Discord
    and most clients render two adjacent regional indicators as a flag when
    the pair matches a real ISO code."""
    return " ".join(chr(_REGIONAL_INDICATOR_A + (ord(letter) - ord("A"))) for letter in word.upper())


def get_flair_reaction(team: str | None, username: str, choice_fn=random.choice) -> str:
    """A silly reaction to someone setting a team flair - unlike get_zinger,
    this never returns None, since every flair pick deserves some kind of
    response, not just the handful of teams with a dedicated roast on file."""
    categories = [_GENERIC_FLAIR_LINES, [_spell_in_emoji(word) for word in _EMOJI_LETTER_WORDS]]
    team_options = _ZINGERS.get(team.strip().lower()) if team else None
    if team_options:
        categories.append(team_options)
    line = choice_fn(choice_fn(categories))
    return line.format(user=username)


# The group signed off on these being crass (2026-10). Keep them aimed at
# people's bets, records and decision-making - never slurs or who someone is.
_KNOCKOUT_ZINGERS = [
    "{user} rode {bet} straight into a fucking wall.",
    "{bet}?? {user}, what the fuck were you thinking.",
    "{user}'s parlay just got taken out back and shot. Cause of death: {bet}.",
    "Down goes {user}. {bet} was dogshit and everyone knew it but you.",
    "{user} bet the fake house on {bet} and the house said get fucked.",
    "Holy shit {user}, {bet}? You deserved that.",
    "{user} is done. {bet} pissed all over the whole parlay.",
    "That {bet} pick just shit the bed and {user} is lying in it.",
    "{user} really thought {bet} was a lock. It was a fucking anchor.",
    "{bet} - the last words of {user}'s dumbass parlay.",
]


def get_knockout_zinger(mention: str, bet_description: str, choice_fn=random.choice) -> str:
    """A one-liner roasting the specific pick that just busted a parlay -
    mention should be a Discord mention string like "<@123>" so it renders
    inline as a real ping rather than plain text, and bet_description a short
    pick summary like "Texas -6.5 (-110)" (see
    formatting.format_selection_button_label)."""
    return choice_fn(_KNOCKOUT_ZINGERS).format(user=mention, bet=bet_description)


_TRASH_TALK_BUSTED_BET = [
    "{user} put money on {bet}. Fake money, sure, but still the dumbest shit I've seen all week.",
    "Daily reminder that {user} bet {bet}. Absolute clown shit.",
    "{user}, {bet}? Were you drunk or just like this?",
    "Somewhere a sportsbook is framing {user}'s {bet} ticket and laughing its ass off.",
    "{user} still hasn't apologized to the group for {bet}. Disgraceful.",
]
_TRASH_TALK_LAST_PLACE = [
    "{user} is dead fucking last at {balance}. Delete the app.",
    "Somebody check on {user}, rotting in last place at {balance}.",
    "{user} at {balance} and still running their mouth with picks. Shut the fuck up.",
]
_TRASH_TALK_LEADER = [
    "{user} on top at {balance} acting like a genius. Lucky as shit and it won't last.",
    "Enjoy first place while it lasts, {user}. The books are coming for your ass.",
    "{user} up to {balance} and already insufferable. Somebody humble this asshole.",
]
_TRASH_TALK_NO_BETS = [
    "{user} opted in and hasn't placed a single bet. Scared money don't make money, you spineless fuck.",
    "{user} sitting on {balance} like it's a fucking 401k. Bet something, coward.",
    "{user} joined just to watch. Get the fuck in the game.",
]
_TRASH_TALK_GENERIC = [
    "{user} has the betting instincts of a drunk raccoon.",
    "Every time {user} locks a pick, Vegas sends a thank-you card and a fruit basket.",
    "{user}'s whole strategy is vibes, Fireball and poor fucking decisions.",
    "If {user} likes a team this week, hammer the other side. Free fucking money.",
    "{user} picks games like they're throwing darts blindfolded. And missing the board.",
    "{user} couldn't hit a parlay if the games were already over.",
]


def get_trash_talk(
    mention: str,
    balance_text: str,
    busted_bets: list[str],
    has_bets: bool,
    is_last: bool,
    is_leader: bool,
    choice_fn=random.choice,
) -> str:
    """An unprompted jab at one player, drawn from whichever of their week's
    sore spots apply (a busted bet named outright, last place, first place,
    opted in but never bet) plus a generic pool, so it reads like it was
    written about them rather than at a random name."""
    categories = [_TRASH_TALK_GENERIC]
    if busted_bets:
        categories.append(_TRASH_TALK_BUSTED_BET)
    if not has_bets:
        categories.append(_TRASH_TALK_NO_BETS)
    if is_last:
        categories.append(_TRASH_TALK_LAST_PLACE)
    if is_leader:
        categories.append(_TRASH_TALK_LEADER)
    template = choice_fn(choice_fn(categories))
    bet = choice_fn(busted_bets) if busted_bets else ""
    return template.format(user=mention, balance=balance_text, bet=bet)
