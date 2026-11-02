"""Parser v1: plain English to the JSON query format, with fixed rules.

The question is normalised (lower case, no accents or punctuation), split into
sequence steps at connectors such as "that led to" or "followed by", and each
step is matched against a lexicon of phrases, in order, so that "left back" is
used up before "left" could be read as a channel. Player and team names come
from the data: full names, and parts of names that point to one player
(docs/methodology/05_rule_parser.md).
"""
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from .config import DataConfig
from .query import validate

# "Led to" with no time given: how long to look for the next step when the
# possession changes (our choice; a little longer than the 10 s transition).
DEFAULT_WINDOW_S = 15.0

# Phrases and the conditions they stand for, tried from top to bottom; a
# matched phrase is removed so later phrases cannot reuse its words. Phrases
# match whole words only. P is an optional plural ending.
P = r"(?:e?s)?"
LEXICON = [
    # Roles, before sides and channels
    (r"left (?:full |wing )?backs?|lwb|lb", {"role_group": "FB", "role_side": "left"}),
    (r"right (?:full |wing )?backs?|rwb|rb", {"role_group": "FB", "role_side": "right"}),
    (r"(?:full|wing) ?backs?", {"role_group": "FB"}),
    (r"left (?:centre|center) ?backs?", {"role_group": "CB", "role_side": "left"}),
    (r"right (?:centre|center) ?backs?", {"role_group": "CB", "role_side": "right"}),
    (r"(?:centre|center) ?backs?|central defenders?|cbs?", {"role_group": "CB"}),
    (r"goal ?keepers?|keepers?|gks?", {"role_group": "GK"}),
    (r"(?:defensive|holding) midfielders?|number 6|no 6", {"role_group": "DM"}),
    (r"attacking midfielders?|number 10|no 10", {"role_group": "AM"}),
    (r"(?:central )?midfielders?", {"role_group": ["DM", "CM", "AM"]}),
    (r"left wingers?", {"role_group": "W", "role_side": "left"}),
    (r"right wingers?", {"role_group": "W", "role_side": "right"}),
    (r"wingers?|wide players?", {"role_group": "W"}),
    (r"strikers?|(?:centre|center) forwards?|number 9|no 9", {"role_group": "ST"}),

    # Derived actions
    (rf"turnovers?|(?:lost|lose|losing|loses) (?:the )?(?:ball|possession)|(?:ball|possession) loss{P}",
     {"turnover": True}),
    (r"regains?|(?:won|win|winning|wins) (?:the )?ball(?: back)?|ball wins?|recovered the ball", {"regain": True}),
    (r"box entr(?:y|ies)|entr(?:y|ies) into the (?:box|penalty area)|into the (?:penalty )?(?:box|area)",
     {"box_entry": True}),
    (r"progressive", {"progressive": True}),

    # How the possession started ("shots from corners"), before the set pieces themselves
    (r"from (?:a |the )?corners?", {"play_pattern": "From Corner"}),
    (r"from (?:a |the )?free ?kicks?", {"play_pattern": "From Free Kick"}),
    (r"from (?:a |the )?throw ?ins?", {"play_pattern": "From Throw In"}),
    (r"from (?:a |the )?goal ?kicks?", {"play_pattern": "From Goal Kick"}),

    # Set pieces, before "goal"
    (r"corners?(?: kicks?)?", {"set_piece_type": "corner"}),
    (r"free ?kicks?", {"set_piece_type": "free_kick"}),
    (r"throw ?ins?", {"set_piece_type": "throw_in"}),
    (r"goal ?kicks?", {"set_piece_type": "goal_kick"}),
    (r"penalt(?:y|ies)|pens?", {"set_piece_type": "penalty"}),

    # Passes and shots with a qualifier
    (r"through ?balls?|through pass(?:es)?", {"action": "pass", "through_ball": True}),
    (rf"key pass{P}|chances? created", {"action": "pass", "key_pass": True}),
    (rf"switch{P} of play|switch{P}", {"action": "pass", "switch": True}),
    (r"cut ?backs?", {"action": "pass", "cutback": True}),
    (rf"cross{P}|crossed", {"action": "pass", "cross": True}),
    (r"assists?", {"action": "pass", "assist": True}),
    (r"headers?|headed", {"header": True}),
    (r"shots? on target", {"action": "shot", "outcome_detail": ["goal", "on_target"]}),
    (r"shots? off target", {"action": "shot", "outcome_detail": "off_target"}),
    (r"blocked shots?|shots? (?:that were |was )?blocked", {"action": "shot", "outcome_detail": "blocked"}),
    (r"goals? conceded|conceded (?:a )?goals?|goals? against us",
     {"action": "shot", "outcome_detail": "goal", "our_team": False}),
    (r"shots? conceded|conceded (?:a )?shots?|shots? against us", {"action": "shot", "our_team": False}),
    (r"attempts? on goal|shots? at goal", {"action": "shot"}),
    (r"goals?|scored|scores?", {"action": "shot", "outcome_detail": "goal"}),
    (r"shots?|shooting|shoot|attempts?", {"action": "shot"}),

    # Phases, before "press" and "block"
    (r"counter ?attacks?|on the counter|counters?", {"phase": "counter_attack"}),
    (r"counter ?press(?:ing|es)?|gegenpress(?:ing)?", {"counterpress": True}),
    (r"high press(?:ing)?|pressing high", {"phase": "high_press"}),
    (r"mid ?block", {"phase": "mid_block"}),
    (r"low ?block", {"phase": "low_block"}),
    (r"in transition|transitions?", {"phase": "transition"}),
    (r"build ?up(?: play)?", {"phase": "build_up"}),
    (r"set ?pieces?|set ?plays?", {"phase": "set_piece"}),

    # Pressure and outcome, before the pressure action
    (r"(?:not|without being|without|while not) under pressure|unpressured|unpressed", {"under_pressure": False}),
    (r"under pressure|pressured|while pressed", {"under_pressure": True}),
    (r"unsuccessful|failed|incomplete|inaccurate|lost", {"outcome": "failure"}),
    (r"successful|completed|complete|accurate|won", {"outcome": "success"}),

    # Other actions
    (rf"pass{P}|passing", {"action": "pass"}),
    (r"carr(?:y|ies)|carried", {"action": "carry"}),
    (r"dribbles?|dribbling|take ?ons?", {"action": "dribble"}),
    (r"tackles?|tackling", {"action": "tackle"}),
    (r"interceptions?|intercepted", {"action": "interception"}),
    (r"(?:ball )?recover(?:y|ies)", {"action": "ball_recovery"}),
    (r"clearances?|cleared", {"action": "clearance"}),
    (r"blocks?", {"action": "block"}),
    (r"aerial duels?|aerials?", {"action": "aerial_duel"}),
    (r"fouls? (?:won|suffered)|fouled", {"action": "foul_won"}),
    (r"fouls?", {"action": "foul_committed"}),
    (rf"miscontrols?|bad touch{P}", {"action": "miscontrol"}),
    (r"dispossessed|dispossessions?", {"action": "dispossessed"}),
    (r"press(?:ing|es)?|pressures?", {"action": "pressure"}),

    # Zones (halves are handled separately: see HALVES)
    (r"(?:final|attacking|last) third", {"third": "attacking"}),
    (r"middle third|midfield third|midfield", {"third": "middle"}),
    (r"(?:defensive|own|first) third", {"third": "defensive"}),
    (r"in(?:side)? the (?:penalty )?(?:box|area)|penalty (?:box|area)|the box", {"in_box": True}),
    (r"left half ?space", {"channel": "left_half_space"}),
    (r"right half ?space", {"channel": "right_half_space"}),
    (r"half ?spaces?", {"channel": ["left_half_space", "right_half_space"]}),
    (r"left (?:hand )?(?:wing|flank|side|touchline)", {"channel": "left_wing"}),
    (r"right (?:hand )?(?:wing|flank|side|touchline)", {"channel": "right_wing"}),
    (r"(?:from|on|down) the left|left", {"channel": ["left_wing", "left_half_space"]}),
    (r"(?:from|on|down) the right|right", {"channel": ["right_wing", "right_half_space"]}),
    (r"through the (?:middle|centre|center)|central(?:ly)?", {"channel": "centre"}),

    # Game state
    (r"winning|leading|ahead|in front", {"game_state": "winning"}),
    (r"losing|behind|trailing", {"game_state": "losing"}),
    (r"drawing|level|tied|all square", {"game_state": "drawing"}),
]
LEXICON = [(re.compile(rf"\b(?:{pattern})\b"), values) for pattern, values in LEXICON]

# Halves, named from the acting team's side ("own"), or as ours or theirs:
# "our half" is the acting team's own half only when we are acting.
HALVES = [
    (r"(?:own|defensive) half", "own"),
    (r"attacking half", "opponent"),
    (r"our half", "ours"),
    (r"(?:their|the opponents?|opponents?|the opposition|opposition|the other) half", "theirs"),
]
HALVES = [(re.compile(rf"\b(?:{pattern})\b"), side) for pattern, side in HALVES]

# Words that say whose events these are.
OURS = re.compile(r"\b(?:we|us|our|ours|leverkusen|bayer)\b")
THEIRS = re.compile(r"\b(?:they|them|their|opponents?|opposition|the other team)\b")

# Connectors between the steps of a sequence.
CONNECTORS = re.compile(r"\b(?:that |which |and )?(?:led|lead|leads|leading) (?:directly )?to\b"
                        r"|\bfollowed by\b|\b(?:that |which )?result(?:ed|ing|s)? in\b|\band then\b|\bthen\b")

STOPWORDS = set("""a an the of in on by from to at for with and or that which who whose where when what how
many all any every each show me find list give get see times moment moments situation situations clip clips
instance instances there were was is are be been being it its his her did do does made make play played
team teams side player players ball this these those season match matches game games please also only
our we us ours their they them""".split())


@dataclass
class Vocabulary:
    """Names the parser recognises: players and opponents, with their short forms."""
    players: dict = field(default_factory=dict)  # alias -> full name
    teams: dict = field(default_factory=dict)  # alias -> full name

    @classmethod
    def from_tags(cls, tags: pd.DataFrame, data: DataConfig = DataConfig()):
        ours = set(tags.player[tags.team.eq(data.focus_team)].dropna())
        players = _aliases(sorted(tags.player.dropna().unique()), prefer=ours)
        teams = _aliases(sorted(set(tags.team) - {data.focus_team}), prefer=set(),
                         ignore={"fc", "vfb", "rb", "fsv", "borussia", "eintracht", "werder", "union", "05", "98"},
                         extra={"bvb": "Borussia Dortmund", "gladbach": "Borussia Mönchengladbach",
                                "cologne": "FC Köln", "union berlin": "Union Berlin",
                                "frankfurt": "Eintracht Frankfurt", "bremen": "Werder Bremen"})
        return cls(players=players, teams=teams)


def _aliases(names, prefer: set, ignore=frozenset(), extra=None) -> dict:
    """Full names, and parts of names that point to one name.

    A part shared by several names is kept only if exactly one of them is in
    `prefer` (our own players), which then wins.
    """
    by_part = {}
    for name in names:
        full = normalise(name)
        words = [w for w in full.split() if len(w) >= 3 and w not in ignore and w not in STOPWORDS]
        for part in {full, *words, " ".join(words[-2:])}:
            if part:
                by_part.setdefault(part, set()).add(name)
    aliases = {}
    for part, owners in by_part.items():
        preferred = owners & prefer
        if len(owners) == 1:
            aliases[part] = next(iter(owners))
        elif len(preferred) == 1:
            aliases[part] = next(iter(preferred))
    aliases.update(extra or {})
    return aliases


class ParseError(ValueError):
    pass


@dataclass
class Parse:
    query: dict
    unparsed: list  # words the parser did not use


UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ORDINALS = {"first": "one", "second": "two", "third": "three", "fifth": "five", "eighth": "eight", "ninth": "nine",
            "twelfth": "twelve", "twentieth": "twenty", "thirtieth": "thirty", "fortieth": "forty",
            "fiftieth": "fifty", "sixtieth": "sixty", "seventieth": "seventy", "eightieth": "eighty",
            "ninetieth": "ninety"}
NUMBER = re.compile(rf"\b(?:({'|'.join(TENS)})(?: ({'|'.join(UNITS[1:10])}))?|({'|'.join(UNITS)}))\b")
ORDINAL_MINUTE = re.compile(r"\b([a-z]+) minute")


def _number_words(text: str) -> str:
    """Spelt-out numbers to digits: "ten seconds" -> "10 seconds", "sixtieth minute" -> "60 minute".

    Ordinals are only converted before "minute", so that "first half" and
    "final third" keep their meaning.
    """
    def ordinal(m):
        word = m.group(1)
        cardinal = ORDINALS.get(word) or (word[:-2] if word.endswith("th") and word[:-2] in UNITS else None)
        return f"{cardinal} minute" if cardinal else m.group(0)

    def number(m):
        if m.group(3):
            return str(UNITS.index(m.group(3)))
        return str(TENS[m.group(1)] + (UNITS.index(m.group(2)) if m.group(2) else 0))

    text = ORDINAL_MINUTE.sub(ordinal, text)
    return NUMBER.sub(number, text)


def normalise(text: str) -> str:
    text = re.sub(r"[’`]", "'", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"[^a-z0-9. ]+", " ", text)
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)  # keep decimal points only
    return _number_words(re.sub(r"\s+", " ", text).strip())


def parse(question: str, vocab: Vocabulary) -> dict:
    """The JSON query for a question; raises ParseError if a part is not understood."""
    return parse_verbose(question, vocab).query


def parse_verbose(question: str, vocab: Vocabulary) -> Parse:
    text, scope = _scope(normalise(question), vocab)
    parts = [p.strip() for p in CONNECTORS.split(text) if p and p.strip()]
    if not parts:
        raise ParseError("empty question")
    steps, unparsed = [], []
    for i, part in enumerate(parts):
        step, rest = _step(part, vocab, first=(i == 0))
        steps.append(step)
        unparsed += rest

    if len(steps) == 1:
        query = {"event": steps[0]["filter"]}
    else:
        _relate(steps)
        query = {"sequence": steps}
    if scope:
        query["matches"] = scope
    validate(query)
    return Parse(query=query, unparsed=unparsed)


def _scope(text: str, vocab: Vocabulary):
    """Opponent and venue, which restrict the matches searched."""
    scope = {}
    home = re.compile(r"\b(?:at home|home (?:games|matches))\b")
    away = re.compile(r"\b(?:away from home|away (?:games|matches)|away)\b")
    if home.search(text):
        scope["venue"] = "home"
        text = home.sub(" ", text)
    elif away.search(text):
        scope["venue"] = "away"
        text = away.sub(" ", text)
    for alias in sorted(vocab.teams, key=len, reverse=True):
        against = re.compile(rf"\b(?:against|vs|versus|v) {re.escape(alias)}\b")
        named = re.compile(rf"\b{re.escape(alias)}\b")
        if against.search(text):
            scope["opponent"] = vocab.teams[alias]
            text = against.sub(" ", text)
            break
        if named.search(text):
            # "Bayern's shots": the opponent is also the team acting.
            scope["opponent"] = vocab.teams[alias]
            text = named.sub(" them ", text)
            break
    return text, scope


def _step(text: str, vocab: Vocabulary, first: bool):
    """The filter of one part, and for later parts how it follows the previous step."""
    step, conditions = {}, {}

    m = re.search(r"\bwithin (\d+(?:\.\d+)?) ?(?:s|sec|secs|seconds?)\b", text)
    if m:
        step["within_s"] = float(m.group(1))
        text = text.replace(m.group(0), " ")
    same = re.compile(r"\b(?:in )?(?:the )?(?:same|that) possession\b")
    if same.search(text):
        step["same_possession"] = True
        text = same.sub(" ", text)

    text = _time(text, conditions)
    text = _names(text, vocab, conditions)
    half = None
    for pattern, side in HALVES:
        if pattern.search(text):
            half = side
            text = pattern.sub(" ", text)
            break
    ours, theirs = bool(OURS.search(text)), bool(THEIRS.search(text))
    for pattern, values in LEXICON:
        if pattern.search(text):
            for name, value in values.items():
                _add(conditions, name, value)
            text = pattern.sub(" ", text)

    recognised = bool(conditions) or half is not None
    if "our_team" not in conditions:
        if ours and not theirs:
            conditions["our_team"] = True
        elif theirs and not ours:
            conditions["our_team"] = False
        elif first and "player" not in conditions:
            conditions["our_team"] = True  # the analyst's own team unless said otherwise
    if half is not None:
        acting_ours = conditions.get("our_team", True)
        conditions["half"] = {"own": "own", "opponent": "opponent",
                              "ours": "own" if acting_ours else "opponent",
                              "theirs": "opponent" if acting_ours else "own"}[half]

    rest = [w for w in THEIRS.sub(" ", OURS.sub(" ", text)).split() if w not in STOPWORDS]
    if not recognised:
        raise ParseError(f"nothing recognised in {text.strip()!r}")
    return ({"filter": conditions} if first else {"filter": conditions, **step}), rest


def _time(text: str, conditions: dict) -> str:
    minute_rules = [
        (r"between (?:the )?(\d+) (?:and|to) (?:the )?(\d+)(?: minutes?)?",
         lambda m: {"gte": int(m.group(1)), "lt": int(m.group(2))}),
        (r"(?:in |during )?(?:the )?(?:last|final) (\d+) minutes?", lambda m: {"gte": 90 - int(m.group(1))}),
        (r"(?:in |during )?(?:the )?first (\d+) minutes?", lambda m: {"lt": int(m.group(1))}),
        (r"(?:after|from|beyond|since) (?:the )?(?:minute )?(\d+)(?: minutes?| mins?)?", lambda m: {"gte": int(m.group(1))}),
        (r"(?:the )?(\d+) minutes? onwards", lambda m: {"gte": int(m.group(1))}),
        (r"(?:before|until|up to) (?:the )?(?:minute )?(\d+)(?: minutes?| mins?)?", lambda m: {"lt": int(m.group(1))}),
    ]
    for pattern, minute in minute_rules:
        m = re.search(rf"\b{pattern}\b", text)
        if m:
            conditions["minute"] = minute(m)
            text = text.replace(m.group(0), " ")
            break
    first_half = re.compile(r"\b(?:in the )?(?:first half|before half ?time)\b")
    second_half = re.compile(r"\b(?:in the )?(?:second half|after half ?time)\b")
    if first_half.search(text):
        conditions["period"] = 1
        text = first_half.sub(" ", text)
    elif second_half.search(text):
        conditions["period"] = 2
        text = second_half.sub(" ", text)
    return text


def _names(text: str, vocab: Vocabulary, conditions: dict) -> str:
    """Player names; "to <player>" is the receiver of a pass."""
    for alias in sorted(vocab.players, key=len, reverse=True):
        receiver = re.compile(rf"\b(?:to|for|towards) {re.escape(alias)}\b")
        named = re.compile(rf"\b{re.escape(alias)}\b")
        if receiver.search(text):
            _add(conditions, "pass_recipient", vocab.players[alias])
            text = receiver.sub(" ", text)
        elif named.search(text):
            _add(conditions, "player", vocab.players[alias])
            text = named.sub(" ", text)
    return text


def _add(conditions: dict, name: str, value):
    """Add a condition; a second value for the same field makes it "any of"."""
    if name not in conditions:
        conditions[name] = value
        return
    old = conditions[name] if isinstance(conditions[name], list) else [conditions[name]]
    new = value if isinstance(value, list) else [value]
    if isinstance(old[0], bool):
        return  # keep the first yes/no
    conditions[name] = list(dict.fromkeys(old + new))


def _relate(steps: list):
    """Link each later step to the previous one: which team, and how far to look."""
    for prev, step in zip(steps, steps[1:]):
        f = step["filter"]
        if "our_team" not in f and "player" not in f:
            # Losing the ball leads to the other team's action; anything else to our own.
            step["team"] = "other" if prev["filter"].get("turnover") else "same"
        if "within_s" not in step and not step.get("same_possession"):
            if step.get("team") == "same":
                step["same_possession"] = True
            else:
                step["within_s"] = DEFAULT_WINDOW_S
