import random
import string
from collections.abc import Mapping, Sequence

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
# people's bets, records and decision-making - never slurs (including
# "retard") or who someone is, and don't assume the target's gender.
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
    "RIP {user}'s parlay. Murdered in cold blood by {bet}, a pick only a braindead idiot would make.",
    "{user} saw {bet} and thought 'free money.' Smooth-brained behavior.",
    "Congrats {user}, {bet} just made you the dumbest motherfucker in the channel.",
    "{bet} lost and {user}'s parlay is now a fucking crime scene.",
    "Who the fuck let {user} bet {bet}? Somebody take the phone away.",
    "{user} trusted {bet}. Room-temperature IQ shit.",
    "{bet} folded like a lawn chair and took {user}'s whole dumbass parlay with it.",
    "Pour one out for {user}. Actually don't, {bet} was too stupid to mourn.",
    "{user} picked {bet} with their whole chest and got kicked square in the teeth.",
    "Breaking: local dumbass {user} loses parlay on {bet}. More at never.",
]


# How often a roast comes from the group's own /admin add-roast lines instead
# of the built-in bank, whenever at least one custom line fits the moment.
CUSTOM_ROAST_ODDS = 0.75


def _pick_least_recent(pool: Sequence[str], recent: Sequence[str], choice_fn) -> str:
    """A random line from `pool` that isn't in `recent`; once every line has
    been used recently, the one used longest ago - so a small pool (like a
    handful of custom roasts) keeps rotating instead of drying up."""
    fresh = [template for template in pool if template not in recent]
    if fresh:
        return choice_fn(fresh)
    last_used = {template: i for i, template in enumerate(recent)}
    return min(pool, key=lambda template: last_used[template])


def _pick_template(
    built_in: list[list[str]], custom: Sequence[str], recent: Sequence[str], choice_fn, random_fn
) -> str:
    if custom and random_fn() < CUSTOM_ROAST_ODDS:
        return _pick_least_recent(custom, recent, choice_fn)
    return _pick_least_recent(choice_fn(built_in), recent, choice_fn)


def get_knockout_zinger(
    mention: str,
    bet_description: str,
    custom: Sequence[str] = (),
    recent: Sequence[str] = (),
    choice_fn=random.choice,
    random_fn=random.random,
) -> tuple[str, str]:
    """A one-liner roasting the specific pick that just busted a parlay -
    mention should be a Discord mention string like "<@123>" so it renders
    inline as a real ping rather than plain text, and bet_description a short
    pick summary like "Texas -6.5 (-110)" (see
    formatting.format_selection_button_label). `custom` lines (from /admin
    add-roast) are preferred per CUSTOM_ROAST_ODDS; anything in `recent` is
    skipped while possible. Returns (line, template)."""
    template = _pick_template([_KNOCKOUT_ZINGERS], custom, recent, choice_fn, random_fn)
    return template.format(user=mention, bet=bet_description), template


_TRASH_TALK_BUSTED_BET = [
    "{user} put money on {bet}. Fake money, sure, but still the dumbest shit I've seen all week.",
    "Daily reminder that {user} bet {bet}. Absolute clown shit.",
    "{user}, {bet}? Were you drunk or just like this?",
    "Somewhere a sportsbook is framing {user}'s {bet} ticket and laughing its ass off.",
    "{user} still hasn't apologized to the group for {bet}. Disgraceful.",
    "Never forget that {user} looked at {bet} and said 'yeah, that one.' Braindead.",
    "{bet}. That's the tweet. That's {user}'s whole fucking legacy.",
    "{user} bet {bet} sober. Let that sink in.",
    "Scientists are still studying how {user} came up with {bet}. Early results: dumbass.",
    "{user}'s {bet} pick should be studied in schools as a warning.",
    "If you ever feel stupid, remember {user} bet {bet}.",
    "{user}, the {bet} pick wasn't a bet, it was a cry for help.",
    "Nobody bring up {bet} around {user}. Actually, fuck it, everyone bring it up.",
    "{user} lost on {bet} and somehow still thinks they're good at this.",
    "Imagine having a brain and still betting {bet}. {user} doesn't have to imagine the second part.",
    "{bet} was the worst pick in this channel since {user}'s last one.",
    "{user} put {bet} in a parlay on purpose. Not a typo. On purpose.",
    "The {bet} pick was so bad the books sent {user} a sympathy card.",
    "{user} and {bet}: a love story where the dumbass gets fucked at the end.",
    "Every time someone says 'lock of the week,' think of {user} and {bet}. Then laugh.",
]
_TRASH_TALK_LAST_PLACE = [
    "{user} is dead fucking last at {balance}. Delete the app.",
    "Somebody check on {user}, rotting in last place at {balance}.",
    "{user} at {balance} and still running their mouth with picks. Shut the fuck up.",
    "{user} finished last at {balance}. A coin flip would've done better, you smooth-brained fuck.",
    "Last place, {balance}. {user}, that's not bad luck, that's being a dumbass with consistency.",
    "{user} at {balance}: proof that confidence and intelligence are unrelated.",
    "Dead last at {balance}. {user}, the floor is down there, keep digging.",
    "{user} took $1,000 and turned it into {balance}. Fucking magician.",
    "{balance} and last place. {user}, your picks should come with a warning label.",
    "{user} is so far in last at {balance} they need a map to find the rest of us.",
    "Bottom of the barrel at {balance}. {user}, we love you, but you're a fucking idiot.",
    "{user} at {balance}. The group chat's designated cautionary tale.",
]
_TRASH_TALK_LEADER = [
    "{user} on top at {balance} acting like a genius. Lucky as shit and it won't last.",
    "Enjoy first place while it lasts, {user}. The books are coming for your ass.",
    "{user} up to {balance} and already insufferable. Somebody humble this asshole.",
    "{user} is in first at {balance}. Even a broken clock, you lucky fuck.",
    "First place {user} at {balance} about to start giving everyone 'advice.' Nobody asked.",
    "{user} up top at {balance}. A blind squirrel found a nut and won't shut up about it.",
    "{balance} and first place. {user}, don't get cocky, you're still a dumbass.",
    "{user} won the week at {balance}. Somebody check their phone for a cheat code.",
    "{user} on top at {balance}, peaking way too fucking early.",
    "Look at {user} at {balance}, strutting like they didn't hit on pure dumb luck.",
    "{user} is leading at {balance}. The regression is going to be fucking beautiful.",
    "First place {user}. Screenshot it, it's never happening again.",
]
_TRASH_TALK_NO_BETS = [
    "{user} opted in and hasn't placed a single bet. Scared money don't make money, you spineless fuck.",
    "{user} sitting on {balance} like it's a fucking 401k. Bet something, coward.",
    "{user} joined just to watch. Get the fuck in the game.",
    "{user} opted in and froze like a deer in headlights. Pick a fucking team.",
    "Zero bets from {user}. Bold strategy, losing by not even showing up.",
    "{user} has {balance} and zero guts. Place a bet.",
    "{user} is just here for the vibes. Nobody invited the vibes, bet something.",
    "Still no bets from {user}. Did you forget how to read odds, dumbass?",
    "{user} opted in and then ghosted. Typical.",
    "{user}, the money isn't going to bet itself, you absolute turnip.",
    "{user} holding {balance} like a squirrel with a nut. Spend it, coward.",
    "Opted in, bet nothing. {user} is the human equivalent of a participation trophy.",
]
_TRASH_TALK_GENERIC = [
    "{user} has the betting instincts of a drunk raccoon.",
    "Every time {user} locks a pick, Vegas sends a thank-you card and a fruit basket.",
    "{user}'s whole strategy is vibes, Fireball and poor fucking decisions.",
    "If {user} likes a team this week, hammer the other side. Free fucking money.",
    "{user} picks games like they're throwing darts blindfolded. And missing the board.",
    "{user} couldn't hit a parlay if the games were already over.",
    "{user} is the reason sportsbooks have such nice buildings.",
    "{user} has a room-temperature IQ and a sub-zero win rate.",
    "{user} reads the injury report like it's in Latin. Braindead.",
    "{user} thinks a moneyline is something you stand in at the bank.",
    "{user}'s picks are so bad they should be illegal.",
    "{user} is smooth-brained enough to bet a team because the jerseys look cool.",
    "Fade {user}. Always fade {user}. Fading {user} is a retirement plan.",
    "{user} could lose a bet on a game that already finished.",
    "{user} has never met a bad line they didn't fucking love.",
    "{user} bets like someone who just learned what football is.",
    "{user} watches one highlight and thinks they're a fucking scout.",
    "{user}'s betting record is a crime against math.",
    "{user} confidently wrong is still the most reliable thing in this channel.",
    "{user}, the parlay gods aren't punishing you. You're just a dumbass.",
    "{user}'s hot take this week will age like milk in a hot car.",
    "{user} has the strategic mind of a golden retriever chasing a car.",
    "{user} is one bad parlay away from a GoFundMe.",
    "Every time {user} says 'trust me,' a bookie gets their wings.",
    "{user} couldn't handicap a game between Alabama and a high school JV team.",
    "{user}'s picks have the structural integrity of a wet paper bag.",
    "{user} bets with their heart, and their heart is a fucking idiot.",
    "{user}, the spread is not a suggestion, you braindead fuck.",
    "{user} treats every Saturday like a hostage negotiation with their own bankroll.",
    "{user} is living proof you can lose fake money and still feel real shame.",
    "{user} doesn't do research, they do vibes and regret.",
    "{user} picks underdogs like someone who's never watched a fourth quarter.",
    "{user} thinks 'the over' is a lifestyle. It's not, dumbass.",
    "If {user} played quarterback they'd throw picks to their own bench.",
    "{user}'s betting advice is a great way to lose friends and money.",
    "{user} has the football IQ of a traffic cone.",
    "{user} would bet the under on their own birthday.",
    "{user}, delete your picks. Delete your account. Delete the whole fucking thing.",
    "{user} is the human equivalent of a missed extra point.",
    "{user} is what happens when confidence has no supervision.",
]


def get_trash_talk(
    mention: str,
    balance_text: str,
    busted_bets: list[str],
    has_bets: bool,
    is_last: bool,
    is_leader: bool,
    recent: Sequence[str] = (),
    custom: Mapping[str, Sequence[str]] = {},
    choice_fn=random.choice,
    random_fn=random.random,
) -> tuple[str, str]:
    """An unprompted jab at one player, drawn from whichever of their week's
    sore spots apply (a busted bet named outright, last place, first place,
    opted in but never bet) plus a generic pool, so it reads like it was
    written about them rather than at a random name. `custom` lines from
    /admin add-roast (keyed by category) are preferred per CUSTOM_ROAST_ODDS
    when any fit; anything in `recent` is skipped while possible. Returns
    (message, template) so the caller can remember which line it used."""
    applicable = ["generic"]
    if busted_bets:
        applicable.append("busted_bet")
    if not has_bets:
        applicable.append("no_bets")
    if is_last:
        applicable.append("last_place")
    if is_leader:
        applicable.append("leader")
    built_in = [ROAST_CATEGORIES[category][0] for category in applicable]
    custom_lines = [line for category in applicable for line in custom.get(category, ())]
    template = _pick_template(built_in, custom_lines, recent, choice_fn, random_fn)
    bet = choice_fn(busted_bets) if busted_bets else ""
    return template.format(user=mention, balance=balance_text, bet=bet), template


# Every category /admin add-roast can add to: (built-in pool, label shown in
# Discord, placeholders a line in it may use). Knockout lines only ever get
# {user} and {bet}; the daily-roast categories get {balance} too, and {bet}
# only exists when the target actually has a busted bet.
ROAST_CATEGORIES: dict[str, tuple[list[str], str, frozenset[str]]] = {
    "generic": (_TRASH_TALK_GENERIC, "Any time", frozenset({"user", "balance"})),
    "busted_bet": (_TRASH_TALK_BUSTED_BET, "Has a busted bet", frozenset({"user", "balance", "bet"})),
    "no_bets": (_TRASH_TALK_NO_BETS, "Opted in, no bets", frozenset({"user", "balance"})),
    "last_place": (_TRASH_TALK_LAST_PLACE, "Last place", frozenset({"user", "balance"})),
    "leader": (_TRASH_TALK_LEADER, "First place", frozenset({"user", "balance"})),
    "knockout": (_KNOCKOUT_ZINGERS, "Parlay knockout alert", frozenset({"user", "bet"})),
}

MAX_ROAST_LENGTH = 300


def validate_roast_template(category: str, template: str) -> str | None:
    """Why a submitted roast line can't be used, or None if it's fine. Catches
    anything that would blow up at .format() time - a typo'd placeholder or
    a stray brace - so a bad line is rejected when it's added, not when it
    crashes a roast weeks later."""
    if category not in ROAST_CATEGORIES:
        return f"Unknown category `{category}`."
    if len(template) > MAX_ROAST_LENGTH:
        return f"Keep it under {MAX_ROAST_LENGTH} characters."
    allowed = ROAST_CATEGORIES[category][2]
    try:
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}
    except ValueError:
        return "Unbalanced `{` or `}` - placeholders look like `{user}`."
    if "user" not in fields:
        return "Include `{user}` so the bot knows where the @mention goes."
    unknown = fields - allowed
    if unknown:
        allowed_text = ", ".join(f"`{{{name}}}`" for name in sorted(allowed))
        return f"`{{{sorted(unknown)[0]}}}` doesn't work here. This category can use {allowed_text}."
    return None
