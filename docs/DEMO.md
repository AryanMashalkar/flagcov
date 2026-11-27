# FlagCov demo video: shot list and voiceover (2:30)

**Goal:** in 150 seconds a judge should feel three things: *"that's a real problem"*, *"that's clever"* and *"it actually works on real Flagsmith"*.

Record in **your own voice**. Talk like you're showing a friend, not reading a script. The lines below are a guide; say them your way. Short sentences, a pause before each reveal.

---

## Setup before recording (10 minutes)

- **Screen:** 1920×1080, terminal font size 18+, dark theme, hide desktop icons and notifications (Windows: Focus Assist on).
- **Recorder:** OBS Studio (free) or Windows Game Bar (`Win + Alt + R`). Record each scene separately; it's much easier to redo one.
- **Mic:** any headset. Record in a quiet room. In OBS add the *Noise Suppression* filter.
- **Windows open, in this order:**
  1. a terminal in `flagcov/examples/demo_shop`
  2. VS Code with `examples/demo_shop/shop.py`
  3. the browser on PR #1 (<https://github.com/AryanMashalkar/flagcov/pull/1>), scrolled to the FlagCov comment
  4. the GitHub Actions run of **Self-hosted Flagsmith end-to-end** (or your local self-hosted Flagsmith dashboard if Docker works)
- **Reset the demo:** `git stash` any experiments; delete `.flagcov/`.
- **Editing:** CapCut or DaVinci Resolve (both free). Add zoom-ins on the key lines (the 10%, the crash). Background music very low, or none.

---

## Scene 1: The hook (0:00 to 0:20)

**Screen:** black, then a news headline style card: *"Knight Capital: $440 million lost in 45 minutes (2012)"*. Then cut to your face cam or the terminal.

**Voiceover:**
> "In 2012 Knight Capital lost four hundred and forty million dollars in forty-five minutes. The cause? A reused feature flag switched on old code that no test had touched in years.
> We all measure line coverage. Nobody measures **flag coverage**. So I built it."

**Title card (2 s):** `FlagCov: code coverage for feature flags` + Flagsmith logo + "Track 03".

---

## Scene 2: Green tests, false confidence (0:20 to 0:40)

**Screen:** terminal. Type `pytest`. *4 passed* in green. Then show `shop.py` in VS Code, scroll to the `checkout_flow` branches (classic / one_page / express / invoice).

**Voiceover:**
> "Here's a little shop. Its checkout flow is a Flagsmith flag with three variants, plus a special version for enterprise customers. The tests are green. Looks safe, right?"

---

## Scene 3: The reveal (0:40 to 1:10), the wow moment

**Screen:** type slowly:
```
pytest --flagcov --flagcov-env environment.json --flagcov-scan .
```
Let the table print. **Zoom in** on the red `express  NOT TESTED  10% of prod traffic` line, then on `Riskiest flag`, then on `missing from Flagsmith: recommendation_v2`.

**Voiceover:**
> "Same tests, one extra flag. FlagCov recorded every flag the tests read and compared it with what Flagsmith is really serving.
> *(pause)* Ten percent of real checkouts go through **express**, and not a single test has ever run it. Enterprise customers get a path nobody tested either.
> And look at the bottom: the code reads `recommendation_v2`, a flag that doesn't even exist in Flagsmith. A typo that silently returns the default forever."

---

## Scene 4: It writes the test, and the test finds a bug (1:10 to 1:40)

**Screen:** open `.flagcov/test_flagcov_stubs.py`. Copy the generated `express` test into `test_express.py`, add one line:
```python
assert checkout(cart_total=650, user_id="u1", city="delhi")["eta_days"] > 0
```
Run `pytest test_express.py`. **Red ZeroDivisionError.** Hold on it for a second.

**Voiceover:**
> "FlagCov doesn't just complain, it writes the missing tests. I paste this one in, add one assert, and run it...
> *(pause)* Crash. Division by zero, for any city without express couriers. That bug is live for one in ten customers, and our green test suite would never have found it."

Then fix it on screen (`EXPRESS_COURIER_SLOTS.get(city) or 1`, or add `"delhi": 2`), re-run, green.
> "One-line fix. Green, and this time it means something."

---

## Scene 5: Real self-hosted Flagsmith (1:40 to 2:05)

**Screen:** the GitHub Actions run **Self-hosted Flagsmith end-to-end**: expand the step that prints the live document (`checkout_flow ... ('one_page', 30.0), ('express', 10.0)`, `segments: ['enterprise']`) and the green "Live self-hosted report verified" step.
If your local Docker works, show the Flagsmith dashboard instead: change `express` from 10% to 25%, re-run, and the report says 25%.

**Voiceover:**
> "This isn't a mock. Every push boots the open-source Flagsmith image, seeds it through Flagsmith's own API, and FlagCov reads the live environment document: the real weights, the real segment rules. Flagsmith is the source of truth; FlagCov just asks the question nobody was asking."

**Optional power move (+10 s, strongly recommended):** open the **Dogfood** workflow run summary.
> "And because Flagsmith reads its own flags exactly this way, I ran FlagCov on 690 of Flagsmith's own tests. Three flags are only ever tested switched on, while the defaults Flagsmith ships have them switched off. Even the people who build feature flags can't see this without a tool."

---

## Scene 6: Where teams will actually see it (2:05 to 2:20)

**Screen:** PR #1 in the browser. Scroll the FlagCov comment: the table, the kill-switch warning, the collapsible "Copy-paste tests".

**Voiceover:**
> "In a real team you'd see it here: on every pull request. It focuses on the flags that PR touches, tells you how much production traffic is untested, and hands you the tests. One line in your workflow."

---

## Scene 7: Close (2:20 to 2:30)

**Screen:** README top with the GIF and badges, then the terminal `pip install flagcov`.

**Voiceover:**
> "FlagCov. Line coverage tells you what your code ran. Flag coverage tells you what your **users** will run. It's open source, it works with self-hosted Flagsmith today, and it's one `pip install` away."

**End card (3 s):** repo URL · `pytest --flagcov` · Toggle Wars 2026.

---

## Things that make judges go "wow" (and things to avoid)

- **Do:** pause half a second before each reveal (the 10%, the crash). Silence sells it.
- **Do:** zoom in on numbers. Judges watch on laptops.
- **Do:** say "self-hosted" and "Flagsmith's own engine" out loud. It's the Track 03 checklist.
- **Don't:** read the README aloud, show `pip install` output scrolling, or go over 3 minutes.
- **Don't:** claim anything not on screen. Every number in this script is real output.
