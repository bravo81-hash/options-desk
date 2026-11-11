"""The rule book: every rule the desk applies, in one place, each with what it is, why it is there and who set it. The numbers are
read from the code that enforces them (a14rules, the strategy cards, readiness, the personal limits), so this page can't drift.
Reference only: it changes nothing."""
from . import a14rules, f49, limitcfg, process, readiness
from .positions import CARDS

YOU2, YOU10, YOU11, DESK = "You, 2 Nov 2026", "You, 10 Nov 2026", "You, 11 Nov 2026", "Desk default"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _r(name, rule, what, why, who, where=""):
    return {"name": name, "rule": rule, "what": what, "why": why, "who": who, "where": where}


def book():
    R, L = a14rules.rule(), limitcfg.current()
    one = lambda v: max(v.values()) if isinstance(v, dict) and v else v  # noqa: E731
    V = {k: one(v) for k, v in L["values"].items()}
    cap, capf, capt, stress, move = V["cap:A14"], V["cap:F49"], V["cap:total"], V["stress"], L["move"]
    pc = lambda v: "not set" if v is None else f"{v:g}%"  # noqa: E731
    full2 = int((cap or 0) // R["worst_nav"]) if cap else None
    wait = {p["key"]: p for p in L["pending"]}
    soon = lambda k: f" Changes to {pc(wait[k]['new'])} from {wait[k]['effective']}." if k in wait else ""  # noqa: E731

    limits = [
        _r("A14 worst-case cap", f"All open A14 ids, each at its worst case, add to no more than {pc(cap)} of NAV, per account." + soon("cap:A14"),
           "Worst case is what an id loses if the index finishes at the worst possible price, whatever happens to volatility. The cap adds those up.",
           f"Before the cap, the ladder's worst cases could add up to most of an account, and one bad session could take a large part of it. The cap sets the most a bad month can take. At full size it fits {full2} ids." if full2 is not None else "Sets the most a bad month can take.",
           YOU10 + " (yours to change, above)", "Now → Am I within my limits?"),
        _r("F49 worst-case cap", f"All open F49 ids, each at its worst case, add to no more than {pc(capf)} of NAV, per account." + soon("cap:F49"),
           "The same measure as the A14 cap, kept apart so each strategy has its own room.",
           "A far-from-the-money tent loses differently from an A14, so you asked for a cap per strategy. Set it before the first F49 trade: while it is not set, nothing limits them.", YOU11, "Now → Am I within my limits?"),
        _r("Cap on every strategy together", f"Every open trade of every strategy, each at its worst case, adds to no more than {pc(capt)} of NAV, per account." + soon("cap:total"),
           "The strategy caps added up, with the strategies that have no cap of their own counted too.",
           "Separate caps can each look fine while the account as a whole carries more than you meant. My suggestion, not yet set by you.", "My suggestion, 11 Nov 2026 (yours to set)", "Now → Am I within my limits?"),
        _r("Stress limit", f"A {move:g}% day either way, with volatility moving with it, costs no more than {pc(stress)} of NAV, per account." + soon("stress"),
           "The desk reprices the whole book, every strategy, for a sudden move up or down and takes the worse side.",
           "The worst-case caps are about expiry. This one is about tomorrow morning: a fall like 5 Nov 2026 (SPX −4.4%) comes in a single session, long before expiry, and hits every strategy at once.", YOU10, "Now → Am I within my limits?"),
        _r("Over any limit", "No new id while an account is over a cap or the stress limit.", "The ladder shows 0 lots and the ribbon says the book is over your limits.",
           "Both accounts trade the same lots, so one account over its limit stops new ids in both.", YOU10, "Actions → A14 ladder"),
        _r("Changing a limit", "A tighter limit applies at once. A looser one, or removing one, applies from the next US session. Every change is kept with its date.",
           "You change them in the panel at the top of this page.",
           "A cap that can be raised in the minute you want to open a trade stops nothing. The one-session wait keeps the decision apart from the trade.", YOU11 + " (the wait was my suggestion)", "Rules → Change your limits"),
    ]

    a14 = [
        _r("Size of one id", f"At full size an id loses {R['stop_nav']:g}% of NAV at its stop, which makes its worst case {R['worst_nav']:g}% of NAV.",
           "Size is set by what the stop can lose, not by margin or by how good the trade looks.", "Before this rule, size grew with confidence, and size added later roughly doubled the risk an id started with, which halved the return on the risk actually carried.", YOU2, "Actions → A14 ladder"),
        _r("Same lots in every account", "Both accounts trade the same lots, worked out on the smaller NAV.", "The smaller account sets the size, so neither goes over the rule.",
           "One decision, one size. Different lots per account made the two books drift apart and doubled the tracking.", YOU2 + " (my choice of the smaller account)"),
        _r("Readiness scales it", "Full, three-quarter, half, quarter or stand aside: only the readiness bar changes the size.", "The lots on the ladder are the full-size lots times the readiness step.",
           "One size authority. No other panel, signal or feeling adds to or cuts the size.", "You, 22 Oct 2026", "Ribbon"),
        _r("Target", f"Close at +{R['target']:g}% of margin.", "A resting order can do this while you sleep: the Trade plan gives the price.",
           "Over 17 years the target is what makes the strategy work: with no target the model earns about 1% a year. +7% beat +10% and beat holding longer.", YOU2, "Risk grid → Trade plan"),
        _r("Hard stop", f"Close at −{R['stop']:g}% of margin.", "Checked every day, not only on adjustment days.",
           "Checking stops only on window days tripled the trades that lost more than half their margin (0.6% to 1.8%).", YOU2, "Risk grid → Trade plan"),
        _r("Time stop", f"Out by {R['time_dte']} days to expiry, whatever the P&L.", "The last week is where a small index move swings the P&L most (gamma).",
           "Leaving at 7 DTE beat 2 DTE at every entry length and halved the big losses.", YOU2 + " (my choice between 7 and 2)", "Risk grid → Trade plan"),
        _r("No added size", "Never add lots to an open id. New risk is always a new id.", "An id keeps the lots it was opened with for its whole life.",
           "Adding to open ids more than doubled the book's worst case in the weeks before the 5 Nov 2026 fall.", YOU2),
        _r("Ladder cap", f"At most {R['cap']} open ids per ticker and account.", "No new id on a ticker that already has that many.",
           "Capping at 4 cost almost nothing in the model and cut the swings. Your worst-case cap now usually binds first.", YOU2, "Actions → A14 ladder"),
        _r("Entry", f"One id per ticker a week, at the Friday expiry nearest {R['entry_dte']} days ({R['dte_lo']}–{R['dte_hi']}): on the {DAYS[R['entry_day']]}, or earlier in the week when the readiness bar reads full or three-quarter size for that ticker and every account is inside its limits.",
           "A midweek id replaces that week's Friday entry: it changes the timing, not the amount of risk. Now says 'midweek' when the conditions are met.",
           f"Entries at {R['dte_lo']}–{R['dte_hi']} days beat shorter ones, and a −5% shock costs about half as much at 45 days as at 14. You wanted to act on a good market without waiting for Friday; the two fixed conditions define 'good' in advance so it isn't judged in the moment. The entry day itself was never tested.",
           f"{YOU11} (Friday only from 2 Nov; midweek from {R['mid_from']})", "Now → Can I open anything?"),
        _r("Strikes", "The desk's shape: upper long at spot, shorts about 0.3 sd below, lower long further down (SPX 0.38 sd under the shorts, RUT 0.44). No hand-picking.",
           "sd is the model's one-standard-deviation move to expiry, about 7% for SPX over 49 days. The shape is your own median A14 from ONE, in those units.",
           "Wider and narrower shapes were tested; none beat it per unit of drawdown. Fixing it removes one more decision. The far-from-the-money tent is a separate strategy, F49, with its own section below.", YOU2, "Actions → A14 ladder"),
        _r("Tilt", f"The tent sits {R['tilt_sd']:g} sd higher when the index is more than {R['tilt_line']:g}% above its 20-day average, {R['tilt_sd']:g} sd lower when more than {R['tilt_line']:g}% below.",
           "A small lean with the short-term trend. Otherwise centred.", "Three separate regime structures added under a point a trade, so the regime acts through size and this small tilt only.", YOU2),
        _r("Decide line", "At −6% the Trade plan says Decide: adjust if the gates pass, otherwise hold to the stop.", "It is a prompt to look, not an exit.",
           "In the model, leaving A14 this early cost more than it saved; adjusting helped only under the conditions below.", DESK + " (from your ONE history, 24 Oct)", "Risk grid → Trade plan"),
        _r("Adjustment gates", f"Adjust only when the id's delta is beyond ±{R['delta_band']:g} a lot, only when the trade is under +3%, and never at 21 days or less.",
           "Delta a lot is how many dollars one lot gains or loses for a one-point move in the index. Reshaping means moving strikes at the same lots. The Trade plan's Adjust? column reads yes or no from these.",
           f"You asked for a delta trigger in place of fixed weekdays. ±{R['delta_band']:g} a lot is about what a 1.5% index move does to an SPX id; a ±2 band breaks after a 0.8–1.2% fall and would have you adjusting constantly. From your 365 adjustments: on winners they helped 36% of the time, on small moves 44–47%, inside 21 days 38%. Shorts moved down hurt; roll-outs and shorts up helped. The band itself is untested.",
           f"{YOU11} (Monday, Wednesday, Friday until {R['delta_from']})", "Risk grid → Trade plan"),
        _r("Pace exit", "A trade 3 weeks in whose return per day is under half your pace target is flagged 'Exit at next green'.", "It asks you to free the capital at the next close at 0% or better.",
           "You asked on 23 Oct for capital to turn over fast. Tested on 11 Nov in the model since 2009, at the approved size: with this exit the return was about the same (8.1% a year against 8.5%) and the deepest fall smaller (39% against 47%), though it earned less in 2018–26 (5.5% against 7.2%). "
           "Your other idea, closing a slow id only when the ladder is full and a new id is waiting, made no difference (8.4%, 43%): a fresh id did not earn more than the slow one it replaced. So the flag stays as it is.",
           "You, 23 Oct 2026 (tested 11 Nov)", "Risk grid → Capital use"),
    ]

    F = f49
    tent = [
        _r("What it is", f"A put butterfly 1/−2/1 whose shorts sit one at-the-money straddle below the index (about 0.8 sd), at the Friday expiry nearest {R['entry_dte']} days. Upper long {F.UP_X:g} straddles above the shorts, lower long {F.LOW_X:g} below.",
           "The straddle is the at-the-money call plus put for that expiry: the market's own expected move. On 9 Nov that put the SPX tent at 7050/6950/6800.",
           "Your idea of 9 Nov: stay far enough below the market that an ordinary fall doesn't reach the shorts. Name a trade F49 in ONE and the desk reads it on this card.", "You, 9 and 11 Nov 2026", "A14 scanner → F49 tent"),
        _r("Exits", f"Close at +{F.TARGET:g}% of the worst case, on a close below the shorts, or at {F.TIME_DTE} days to expiry, whichever comes first. Never adjusted.",
           "Below the shorts the trade loses until its last two weeks, so the card leaves there.",
           f"In the model the index closed below the shorts in 20% of trades, with a median loss of about 9% of the worst case at that close; held to expiry instead, the deepest fall was 86%. The target was reached first in only 9% of trades: most end at the {F.TIME_DTE}-day exit with about 4–5%.",
           "You, 9 Nov 2026 (as tested)", "Risk grid → Trade plan"),
        _r("Size and entry", f"An id's worst case is {F.WORST_NAV:g}% of NAV at full size, scaled by the readiness bar, the same lots in every account. Fridays only, at most {F.CAP} ids a ticker.",
           "The same sizing as A14, because that is what the test used. The F49 cap in Your limits sits above it.",
           "These are the test's settings carried over, not choices you have made yet: change them if you want different ones. The midweek entry rule is A14's only.", "Carried over from the 9 Nov test (yours to confirm)", "A14 scanner → F49 tent"),
        _r("How much to trust it", "SPX, 2009–2026, desk model: +4.6% a year, deepest fall 10.5%, 82% winners averaging +3.6% against losers averaging −7.7%.",
           "A rally pays at most the credit, about 6% of the worst case.",
           "The result rests on a skew fitted to 18 recorded days and on fills at mid. With the desk's older skew it was +1.8% a year; with doubled costs +0.4%. Treat the first trades as a trial at the smallest size.", "Model, 9 Nov 2026", "A14 scanner → F49 tent"),
    ]

    market = [
        _r("What the bar measures", "The chance SPX falls 5% or more within 21 sessions after days like today. Normally about 16–17%.", "Each input (VIX level, VIX conditions, market warnings, sector rotation) gives its own odds from history; the bar uses the highest.",
           "One number in one language. The inputs overlap, so adding them up would double count.", "You, 22 Oct 2026", "Ribbon → Why"),
        _r("Size from the odds", "Under 17% full size, 17–23% three-quarter, 23–30% half, 30% or more stand aside.", "This is the starting size for any new premium-selling trade.",
           "It is a tilt, not a shield: on 4 Nov it read normal, and the fall came the next day. Your limits are what protect the account.", DESK, "Ribbon"),
        _r("Sit-out days", "Stand aside when HYG falls 1.5% or more in a day, or the VIX is 40 or higher.", "Overrides the odds.", "Credit breaking or panic-level volatility: the days after these were the worst in the history tested.", DESK),
        _r("Term structure (VIX ÷ VIX3M)", "0.834 or less steep and calm; to 0.90 normal; 0.90–1.00 flat, stress building; 1.00 or more backwardation.",
           "When near-term volatility costs as much as longer-term, the market is paying up for protection now.",
           "A14s entered at 0.90+ lost on average since 2009 (model): one step down when flat, stand aside in backwardation. Calendars stand aside from 0.90.", DESK, "Ribbon → Why"),
        _r("Below the 20-day average", "A14: one more step down when the index is below its 20-day average, unless the term structure is normal.", "Short-term trend, per index.",
           "Below the average with a normal term structure was among the model's best A14 cells, so it isn't penalised there.", DESK),
        _r("Front of the curve (VIX9D ÷ VIX)", f"A14: one step down at {readiness.FRONT_LINE:g} or more in a steep or normal term structure.", "Nine-day volatility running close to or above 30-day: stress at the very front.",
           "A14s entered like this did worse in all 16 splits tested since 2011.", DESK),
        _r("Thin RUT premium", "RUT A14: one step down when RVX is 3 points or less above VIX.", "RVX is the Russell's VIX.", "RUT moves about 1.2 times SPX; without extra premium for it, SPX is the better trade.", DESK),
        _r("Calendars and releases", "Calendars: one step down below the 20-day average, and one more with CPI, FOMC, payrolls, PCE or GDP inside 3 days.", "Applies to TimeEdge-style calendars only.",
           "Calendars entered under 0.90 and above the 20-day average averaged about +4% a trade in the model; the rest about −0.6%. Your June 2026 calendar losses were entries into a shock.", DESK),
    ]

    cards = []
    how = {"gated": "adjust only on the gates", "one": "one adjustment, then exit", "never": "never adjusted"}
    for name, c in CARDS.items():
        if name in ("A14", "F49"):
            continue
        bits = [f"stop −{c['stop']}%" if c.get("stop") else "no fixed stop", f"out by {c['time']} DTE" if c.get("time") is not None else "no time stop", how.get(c.get("adjust"), "")]
        cards.append(_r(name, " · ".join(b for b in bits if b) + ".", "The Trade plan labels each open trade from its card.",
                        "Set from your own closed trades in ONE on 24 Oct. These haven't had the full review A14 had: they come next, one at a time.", DESK + " (from your ONE history)", "Risk grid → Trade plan"))

    d = {"ahead": process.AHEAD, "quiet": abs(process.QUIET), "rough": abs(process.ROUGH)}
    score = [
        _r("No profit target", "The 1%-a-week target is retired. The scoreboard shows fall from peak, rules followed and your reads.", "Nothing on the Now screen is in dollars.",
           "At a size the accounts survive, the model earns about 0.15% a week, so a 1% target could only be met by oversizing.", YOU10, "P&L → Scoreboard"),
        _r("Rules followed", "Every decision is checked against the rules in force that day, from your fills in ONE. Nothing is typed.", "A decision reads 'as planned' or 'differed', with the reason.",
           "It scores what you control. A rule written later never marks down an earlier trade.", YOU10, "Now → How I'm doing"),
        _r("Your read of the week", f"One tap a day: quiet, normal or rough over the next {d['ahead']} sessions.",
           f"Quiet: SPX never closes more than {d['quiet']:g}% below that day's close. Rough: it closes {d['rough']:g}% or more lower at some point. Normal: in between.",
           "It builds a record of how well you and the desk read the market, against always saying quiet. It takes about 20 scored weeks to mean anything.", YOU10, "Now → Your read"),
    ]

    always = [
        _r("Read-only", "The desk never places, changes or cancels an order.", "Every flag is information. Orders are yours, in TWS.", "Your rule from the start.", "You, 10 Oct 2026"),
        _r("Marks must be complete", "A trade is labelled only when every leg has a price; otherwise the last fully priced total is used and dated, or it says Marks incomplete.", "Stops the plan reading a half-priced trade as a profit or a loss.",
           "After hours about half the legs can have no price, and the plan then showed false 'Close: target' labels.", "You, 9 Nov 2026", "Risk grid → Trade plan"),
        _r("Warnings are information", "Event risk, overnight, stress signals and the gap what-if never change size or gates.", "They are there to be read, not obeyed.",
           "Several thresholds in them were my choice and are untested. Only the readiness bar sizes, and only your limits stop.", "You, 1 Nov 2026", "Actions"),
    ]

    return {"sections": [
        {"title": "Your limits", "note": "These sit above everything else.", "rules": limits},
        {"title": "A14", "note": f"SPX and RUT put broken-wing butterflies. In force from {R['from']}.", "rules": a14},
        {"title": "F49", "note": "The far-from-the-money put tent. A trial: tested once, not yet traded.", "rules": tent},
        {"title": "Reading the market", "note": "How the readiness bar gets its size.", "rules": market},
        {"title": "Other strategies", "note": "Card rules only, not yet reviewed in depth.", "rules": cards},
        {"title": "How you are scored", "note": "", "rules": score},
        {"title": "Always", "note": "", "rules": always}]}
