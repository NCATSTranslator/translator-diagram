# Choosing an owner colour

Owner-to-colour mappings live in [`config/owner-colors.csv`](../config/owner-colors.csv),
two columns: `owner`, `color`. Adding a team is a one-line edit to that file and
needs no code change — row order is legend order, and an owner not listed there
gets a fallback colour automatically.

The constraints below are not obvious from the file, and the file cannot carry
comments explaining them: it is parsed as CSV, so a comment row would be read as
an owner.

## Where the file is read from

`load_owner_colors` takes `config/owner-colors.csv` from the working directory or
the nearest directory above it, and falls back to the copy inside the installed
package so that an install with no checkout still has colours. There is only one
copy in the repository; the wheel build maps this file to
`translator_diagram/owner-colors.csv` rather than a second file being kept in
step by hand. `--owner-colors PATH` overrides both.

Note that the *diagram* reads each component's owner from the Google Sheet while
the *dashboard* reads it from `components/<id>.yaml`. Renaming an owner means
renaming it in both places, or the half that still says the old name silently
falls back to a rotating colour.

## The four rules

Three of them are not obvious from the file:

- **Not red, amber, green or teal.** The page spends those on meaning:
  `--bad-bg` is red, `--warn-bg` and `--drift-bg` are amber, `--ok-bg` is
  green, and the dark theme's `--ok-bg` is a deep teal. A team chip in one of
  those reads as a status about the team. CATRAX was orange and DOGSURF was
  green; both moved for this reason, and NCATS left red because `--bad-bg` is
  red.
- **4.5:1 against the text colour.** `text_color_for` picks black or white by
  luminance, and `tests/test_colors.py` fails the build below WCAG AA. The
  chips are 0.75rem, so the 3:1 large-text allowance does not apply.
- **Keep clear of the 0.5 luminance line** that `text_color_for` switches on.
  A colour sitting on it has poor contrast whichever side it lands, and an
  innocent nudge flips the text. Material's Purple 300 sits 0.003 from it.
- **The palette is full.** Its own separation floor is about 31 dE (UI against
  DOGSURF), and after the reserved hues the usable space is the blue-to-magenta
  arc, which five teams already share. A tenth owner has no good colour left;
  `ColorAssigner` will hand it one from `FALLBACK_COLORS`, which none of the
  above constrains. Re-deriving all of them together reaches about 43, and is
  the honest fix when it comes to that.

## Contrast is tested, hue is not

`tests/test_colors.py` fails the build for a colour below 4.5:1 against the
black or white `text_color_for` picks for it, so the second rule enforces
itself. The other three are judgement, and this file is where they are written
down.
