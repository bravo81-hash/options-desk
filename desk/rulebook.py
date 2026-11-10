"""The rule book: every rule the desk applies, in one place, each with what it is, why it is there and who set it. The numbers are
read from the code that enforces them (a14rules, the strategy cards, readiness, the personal limits), so this page can't drift.
Reference only: it changes nothing."""
from . import a14rules, load_config, process, readiness
from .positions import CARDS

YOU2, YOU10, DESK = "You, 2 Nov 2026", "You, 10 Nov 2026", "Desk default"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _r(name, rule, what, why, who, where=""):
    return {"name": name, "rule": rule, "what": what, "why": why, "who": who, "where": where}


def book():
    R, lim = a14rules.rule(), (load_config().get("risk", {}).get("stress") or {})
    cap, stress, move = lim.get("cap_pct"), lim.get("limit_pct"), lim.get("move") or 5
    pc = lambda v: "not set" if v is None else f"{v:g}%"  # noqa: E731
    win = ", ".join(DAYS[d] for d in R["windows"])
    full2 = int((cap or 0) // R["worst_nav"]) if cap else None

    limits = [
        _r("Worst-case cap", f"All open A14 ids, each at its worst case, add to no more than {pc(cap)} of NAV, per account.",
           "Worst case is what an id loses if the index finishes at the worst possible price, whatever happens to volatility. The cap adds those up.",
           f"Before the cap, the ladder's worst cases could add up to most of an account, and one bad session could take a large part of it. The cap sets the most a bad month can take. At full size it fits {full2} ids." if full2 is not None else "Sets the most a bad month can take.",
           YOU10, "Now → Am I within my limits?"),
        _r("Stress limit", f"A {move:g}% day either way, with volatility moving with it, costs no more than {pc(stress)} of NAV, per account.",
           "The desk reprices the whole book for a sudden move up or down and takes the worse side.",
           "The worst-case cap is about expiry. This one is about tomorrow morning: a fall like 5 Nov 2026 (SPX −4.4%) comes in a single session, long before expiry.", YOU10, "Now → Am I within my limits?"),
        _r("Over either limit", "No new id while an account is over the cap or the stress limit.", "The ladder shows 0 lots and the ribbon says the book is over your limits.",
           "Both accounts trade the same lots, so one account over its limit stops new ids in both.", YOU10, "Actions → A14 ladder"),
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
        _r("Ladder cap", f"At most {R['cap']} open ids per ticker and account.", "The ladder skips a Friday when a ticker already has that many.",
           "Capping at 4 cost almost nothing in the model and cut the swings. Your worst-case cap now usually binds first.", YOU2, "Actions → A14 ladder"),
        _r("Entry", f"{DAYS[R['entry_day']]} only, one id per ticker, the Friday expiry nearest {R['entry_dte']} days ({R['dte_lo']}–{R['dte_hi']}).", "One scheduled decision a week instead of one whenever the market looks inviting.",
           f"Entries at {R['dte_lo']}–{R['dte_hi']} days beat shorter ones, and a −5% shock costs about half as much at 45 days as at 14. A fixed day takes timing out of it.", YOU2, "Now → Can I open anything?"),
        _r("Strikes", "The desk's shape: upper long at spot, shorts about 0.3 sd below, lower long further down (SPX 0.38 sd under the shorts, RUT 0.44). No hand-picking.",
           "sd is the model's one-standard-deviation move to expiry, about 7% for SPX over 49 days. The shape is your own median A14 from ONE, in those units.",
           "Wider and narrower shapes were tested; none beat it per unit of drawdown. Fixing it removes one more decision.", YOU2, "Actions → A14 ladder"),
        _r("Tilt", f"The tent sits {R['tilt_sd']:g} sd higher when the index is more than {R['tilt_line']:g}% above its 20-day average, {R['tilt_sd']:g} sd lower when more than {R['tilt_line']:g}% below.",
           "A small lean with the short-term trend. Otherwise centred.", "Three separate regime structures added under a point a trade, so the regime acts through size and this small tilt only.", YOU2),
        _r("Decide line", "At −6% the Trade plan says Decide: adjust if the gates pass, otherwise hold to the stop.", "It is a prompt to look, not an exit.",
           "In the model, leaving A14 this early cost more than it saved; adjusting helped only under the conditions below.", DESK + " (from your ONE history, 24 Oct)", "Risk grid → Trade plan"),
        _r("Adjustment gates", f"Adjust only on {win} (New York), only when the trade is under +3%, only after the index has moved 1.5% or more if the trade is green, and never at 21 days or less.",
           "Reshaping means moving strikes at the same lots. The Trade plan's Adjust? column reads yes, wait or no from these.",
           "From your 365 adjustments: on winners they helped 36% of the time, on small moves 44–47%, inside 21 days 38%. Shorts moved down hurt; roll-outs and shorts up helped.", YOU2, "Risk grid → Trade plan"),
        _r("Pace exit", "A trade 3 weeks in whose return per day is under half your pace target is flagged 'Exit at next green'.", "It asks you to free the capital at the next close at 0% or better.",
           "You asked on 23 Oct for capital to turn over fast. It is outside the 2 Nov rule page, and whether to keep it for A14 is still an open question.", "You, 23 Oct 2026 (open question)", "Risk grid → Capital use"),
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
        if name == "A14":
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
        {"title": "Reading the market", "note": "How the readiness bar gets its size.", "rules": market},
        {"title": "Other strategies", "note": "Card rules only, not yet reviewed in depth.", "rules": cards},
        {"title": "How you are scored", "note": "", "rules": score},
        {"title": "Always", "note": "", "rules": always}]}
