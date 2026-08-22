"""Where this server's numbers come from — the one place that reads config.

Every constant that decides a score, a blocker or an order used to be a
literal in this repo: the 60/40 split (in jobcore), the +5 bonuses (in
jobcore), the 0.5 must-have warning ratio, the one-year experience slack, and
a ``PREFERENCE_TILT = 4`` that encoded the operator's own stated preference
somewhere he could not reach it. They are now values in a shared
``jobhunt.json``, and this module is the seam.

Three rules hold it together:

1. **The scoring path never reads a file.** ``fit.py`` takes a :class:`Bound`
   and does no I/O; this module does the I/O, once, at tool entry. That is
   jobcore's rule (``test_independence`` runs a clean interpreter with cwd
   elsewhere and asserts a score of 100) applied one layer up: the same job
   must score the same on two machines, or a score stops meaning anything.

2. **Bind once per call.** A snapshot is immutable. A config change that
   lands mid-call must not be seen by that call — half a ranking scored under
   old weights and half under new is worse than either.

3. **Defaults are today's literals.** :data:`DEFAULTS` is built from
   jobcore's shipped policy with no file involved, so a bare clone with no
   config anywhere behaves byte-for-byte as this server did before any of
   this existed.

**Pay is read in USD/year and never in lakhs.** ``candidate.pay`` is
denominated per unit system precisely because one shared scalar silently
scored every Uplers job +5 (a $150k figure clears a 24-lakh expectation) and
every Naukri job 0 (a 25-lakh figure never clears a 20,959-dollar one), and
both look exactly like "no salary data". :data:`PAY_UNIT` is the only
denomination this server ever asks for, and asking for the other one raises.

**The shared ``candidate`` block is not his Uplers profile.** His real
platform profile lives on Uplers, the operator owns it, and the only bridge
is ``uplers_sync_profile_from_uplers``, which is confirm-gated. Nothing here
mirrors, syncs or overwrites it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from jobcore import (
    DEFAULT_POLICY,
    DEFAULT_TAXONOMY,
    Salary,
    SalaryConfig,
    ScoringEngine,
)
from jobcore import config as jobcore_config
from jobcore import paths as jobcore_paths

from . import config as server_config

#: The name this server owns in the shared document: ``servers.uplers.*``.
#: It is also the only section ``apply_patch`` will let this server write
#: besides the two shared ones.
SERVER = "uplers"

#: USD/year, used as-is. ``raw_amount_threshold`` is the ceiling above which
#: jobcore treats a figure as raw currency needing division; no real annual
#: salary approaches 10 million, so no division ever fires and the numbers
#: stay dollars. jobcore's default would turn 60,000 into 0.6 lakhs.
USD_YEAR_CONFIG = SalaryConfig(lakhs_multiplier=1.0, raw_amount_threshold=10_000_000.0)


class UsdYearSalary(Salary):
    """jobcore Salary bound to USD/year instead of lakhs/annum."""

    CONFIG = USD_YEAR_CONFIG


#: The ONLY denomination this server reads out of ``candidate.pay``. Not a
#: preference — asking :meth:`jobcore.policy.CandidatePay.for_unit` for the
#: other one is how a lakhs figure would end up scored as dollars.
PAY_UNIT = "usd_per_year"

#: The other one, named here only so a test can assert it is never read.
FOREIGN_PAY_UNIT = "inr_lakhs_per_year"


#: The anchor every displayed path is measured against. Named here rather than
#: passed at each call site so the ~12 places that render a path cannot drift
#: into anchoring against different roots and rendering the same file two ways.
DISPLAY_ANCHOR = server_config.REPO_ROOT


def display_path(raw):
    """A path a reader can act on, that is not this machine's absolute layout.

    A live sweep on 2026-08-22 found ``D:\\Sundeep\\projects\\...`` in this
    server's ``uplers_get_profile`` and ``uplers_config`` results. That is
    wrong twice over: it publishes the box's directory layout into any shared
    transcript, and it is paid for in tokens on every response carrying it.

    RELATIVISE, DO NOT DELETE. "Where is the config file even?" is a documented
    use of ``uplers_config`` - its own docstring points at ``searched`` for
    exactly that - so a ``None`` here would trade a leak for a different defect:
    a field that answers a different question than it looks like. jobcore's
    renderer keeps the answer and drops the layout, in three forms (anchored
    relative, then ``~/...``, then a ``.../a/b/c`` tail), none of which carries
    a drive letter and all of which stay distinguishable from each other - the
    basename fallback it replaced collapsed every entry of ``searched`` to the
    identical string ``jobhunt.json``.

    Delegation, not a copy: ``jobcore.paths.display_path`` is the canonical
    implementation, shared with the naukri server, so the two report the same
    file the same way. jobcore cannot know where its consumer lives, which is
    why the anchor is supplied rather than inferred.

    A NON-ABSOLUTE input is returned untouched. It already carries no machine
    layout, so there is nothing to render, and rendering it anyway would be
    actively wrong: ``os.path.relpath`` resolves a relative string against the
    CURRENT WORKING DIRECTORY, which would turn the sqlite sentinel
    ``":memory:"`` into a run of ``..`` hops that names no file at all. This
    function is called from a dozen sites including error messages, so being
    total matters more than being clever.
    """
    if not raw:
        return raw
    try:
        if not Path(raw).is_absolute():
            return raw
    except (OSError, ValueError, TypeError):
        return raw
    return jobcore_paths.display_path(raw, anchor=DISPLAY_ANCHOR)


#: One path separator, spelled rather than written, because the whole defect
#: below is about how many of them a reader thinks they are looking at.
_SEPARATOR = chr(92)


def repr_spelling(raw):
    """The way ``repr()`` spells *raw* inside an exception message.

    ``OSError.__str__`` renders its ``filename`` through ``repr()``, so a
    Windows path arrives in the message with DOUBLED separators. MEASURED on
    2026-08-22 against a jobhunt.json that existed but could not be read: the
    ``{path}`` half of jobcore's ``cannot read {path}: {exc}`` was correctly
    relativised while the ``{exc}`` half published the full layout, out of the
    same sentence, because every exact-substring scrubber in this family
    searched for the single-separator form and found nothing.

    So this is not a new kind of check - it is ONE MORE SPELLING of a needle
    the scrubber already had. Deliberately not a "looks like a path" hunt:
    a heuristic would eventually eat a platform.uplers.com URL or a quoted
    Windows path inside user content, and a scrubber that mangles correct
    fields does more damage than the leak it was written for.

    On POSIX the two spellings are IDENTICAL - there are no separators to
    double - so the extra needle collapses onto the first and costs nothing.
    """
    return str(raw).replace(_SEPARATOR, _SEPARATOR * 2)


def relativise_paths(text, paths):
    """Exact substitution of *paths*, in BOTH spellings, inside *text*.

    The primitive under :func:`relativise_known_paths`, exposed because three
    of this server's four leak sites compose a message around an exception
    whose path this server never looks inside - the local profile file
    (``profile.load``) and a profile snapshot (``profile_write.load_snapshot``)
    are not config paths, so they are not in ``Loaded.known_paths`` and no
    snapshot-driven substitution can reach them.

    Both spellings render to the SAME string, which is what makes this exact
    rather than clever: the mapping is built here, so a needle is only ever
    replaced by the rendering of the path it actually is.
    """
    rendered = {}
    for raw in paths or ():
        if not raw:
            continue
        raw = str(raw)
        shown = str(display_path(raw))
        rendered[raw] = shown
        rendered[repr_spelling(raw)] = shown
    if not rendered:
        return text
    # Longest first is the upstream's job, and it matters twice over here: a
    # searched path is often a prefix of another, and the doubled spelling is
    # always longer than the single one it shadows.
    return jobcore_paths.relativise_known(
        text, known=rendered, render=rendered.__getitem__
    )


def relativise_known_paths(text, loaded):
    """Render any path jobcore already baked into a composed message.

    A BINDING of ``jobcore.paths.relativise_known``, not a second copy of it.
    This server shipped its own substitution loop in c65f9ef; jobcore took the
    idea upstream in 0f557eb and it is strictly better, so the algorithm here
    is gone and only the two arguments this server knows remain.

    What the upstream adds, and it is not cosmetic: ``Loaded.known_paths``
    includes the PARENT DIRECTORY of the config and of every searched path.
    The local version keyed on ``source`` plus ``searched`` alone, which cannot
    touch the two files jobcore names from that directory - the history ledger
    (``could not append to {ledger}``) and the write lock (``config file locked
    by live PID ... (lock: {lock_file})``). Neither equals ``source``, both
    reach a caller through ``uplers_config().write``, and MEASURED here: the
    lock message published the full temp path with the local implementation in
    place and clean with this one.

    Substitution stays EXACT rather than heuristic - only strings the snapshot
    already knows are paths - which is why a Naukri API route or a
    platform.uplers.com URL in the same sentence is left alone.

    Each known path is now searched for in BOTH spellings; see
    :func:`repr_spelling` for the measurement that made that necessary. That is
    the only change to the algorithm, and it is why the upstream primitive is
    reached through :func:`relativise_paths` rather than called directly.
    """
    return relativise_paths(text, loaded.known_paths)


def relativise_mapping(payload, loaded):
    """:func:`relativise_known_paths` over every string value of a flat dict.

    For jobcore's ``apply_patch`` return, which this server hands back verbatim
    as ``ConfigReport.write`` and which carries a path in three places -
    ``path`` on success, ``ledger_error``, and ``detail`` on a lock conflict.
    Passing that dict through untouched is how a leak survived a sweep that had
    already cleaned every path FIELD on the report beside it.

    Non-string values pass through: the upstream returns anything that is not a
    string unchanged, so this is safe to map over a mixed payload.
    """
    if not isinstance(payload, dict):
        return payload
    return {
        key: relativise_known_paths(value, loaded) for key, value in payload.items()
    }


def _taxonomy_for(scoring):
    """The shared 88-skill taxonomy, plus any vocabulary he added."""
    extension = scoring.skills.taxonomy_extension()
    if not extension:
        return DEFAULT_TAXONOMY
    return DEFAULT_TAXONOMY.extended(extension)


@dataclass(frozen=True)
class Bound:
    """One immutable binding of policy + engine + this server's settings.

    Built once per tool call and passed down. Holding it (rather than
    re-reading) is what makes a ranking internally consistent.
    """

    loaded: Any
    engine: ScoringEngine
    settings: Mapping[str, Any] = field(default_factory=dict)

    # ── the scoring policy, for callers that need it directly ─────────────
    @property
    def scoring(self):
        return self.loaded.policy.scoring

    @property
    def candidate(self):
        return self.loaded.policy.candidate

    @property
    def policy_hash(self) -> str:
        """Scoring AND candidate. Config identity - "is this the same setup"."""
        return self.loaded.policy_hash

    @property
    def scoring_hash(self) -> str:
        """The arithmetic alone, and the one a scored result is stamped with.

        Deliberately not equal to :attr:`policy_hash`: that one also covers the
        candidate block, so comparing a result's stamp against it reports a
        difference that does not exist. This is the comparability field.
        """
        return self.loaded.scoring_hash

    # ── servers.uplers.* accessors ────────────────────────────────────────
    def setting(self, *path, default=None):
        """``bound.setting("must_have", "warn_ratio")``, defaults filled in."""
        node: Any = self.settings
        for part in path:
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def pay_band(self):
        """His pay decisions in USD/year. Never converted, never guessed."""
        return self.candidate.pay.for_unit(PAY_UNIT)

    def configured(self, key: str) -> bool:
        """True when *key* came from the file rather than a shipped default.

        The discriminator has to be provenance, not emptiness: ``candidate.
        notice_period_days`` defaults to 0 and 0 is also a real answer, so
        "is it falsy" would let an unset shared default silently overwrite a
        local profile that says 30.
        """
        return self.loaded.provenance.get(key) == "file"

    def named_but_unanswered(self) -> list[str]:
        """Candidate keys the file NAMES but leaves empty, so local wins.

        Not a warning about a mistake - a generated template writes every key -
        but it must not be silent, because "the file says skills and my skills
        are not being used" is otherwise unexplainable. See
        :func:`effective_profile`.
        """
        out: list[str] = []
        for holder, field_map in ((self.candidate, FIELD_MAP), (self.pay_band(), PAY_FIELD_MAP)):
            for key, _attr in field_map:
                if self.configured(key) and states_nothing(
                    getattr(holder, key.rsplit(".", 1)[1], None)
                ):
                    out.append(key)
        return out

    def notes(self) -> list[str]:
        """Everything about the config a caller must not discover silently."""
        out: list[str] = []
        ld = self.loaded
        unanswered = self.named_but_unanswered()
        if unanswered:
            out.append(
                "config names %d candidate key(s) without answering them (%s); the "
                "local profile is used for those. An empty value in the file is "
                "read as 'not set', never as 'set to nothing'."
                % (len(unanswered), ", ".join(unanswered[:5]))
            )
        if ld.config_error:
            out.append("config: %s (built-in defaults in use)" % ld.config_error)
        for line in ld.tier_c_refusals:
            out.append("config REFUSED: %s" % line)
        for line in ld.warnings:
            out.append("config warning: %s" % line)
        if ld.unknown_keys:
            out.append(
                "config declares %d key(s) nothing reads: %s"
                % (len(ld.unknown_keys), ", ".join(ld.unknown_keys[:5]))
            )
        if ld.external_edit:
            out.append(
                "config was edited outside this tool since the last recorded "
                "revision; scores may differ from the last run (%s)"
                % (ld.external_edit.get("detail") or ld.external_edit)
            )
        if ld.revision_regression:
            out.append("config revision went backwards: %s" % (ld.revision_regression,))
        # Applied to EVERY line rather than to the one known offender: several
        # of these interpolate a jobcore-composed string, and the substitution
        # is a no-op on a line that holds no path anyway.
        return [relativise_known_paths(line, ld) for line in out]


# ── Engine cache ───────────────────────────────────────────────────────────
#
# Keyed by the policy fingerprint hash, which by construction covers exactly
# the inputs that can move a number (scoring, plus the scoring-relevant half
# of candidate). Two loads of an unchanged file reuse one engine; an edit
# builds a new one. The cache is bounded because the number of distinct
# policies a process sees is the number of times he edits the file.

_ENGINES: dict[str, ScoringEngine] = {}
_ENGINE_CACHE_MAX = 32


def engine_for(loaded) -> ScoringEngine:
    """The :class:`ScoringEngine` this policy implies, memoised by fingerprint."""
    # Deliberately the WIDER hash: the engine is built from scoring AND
    # candidate, so scoring_hash would collide two engines that differ in the
    # candidate half. A key wider than the thing it guards is only ever a
    # missed cache hit; a narrower one is a wrong answer.
    key = loaded.policy_hash
    engine = _ENGINES.get(key)
    if engine is None:
        if len(_ENGINES) >= _ENGINE_CACHE_MAX:
            _ENGINES.clear()
        engine = ScoringEngine(
            taxonomy=_taxonomy_for(loaded.policy.scoring),
            salary_cls=UsdYearSalary,
            policy=loaded.policy.scoring,
            candidate=loaded.policy.candidate,
        )
        _ENGINES[key] = engine
    return engine


def invalidate() -> None:
    """Drop the engine cache and jobcore's snapshot cache. Tests and reloads."""
    _ENGINES.clear()
    jobcore_config.invalidate_cache()


def snapshot(*, env: Mapping[str, str] | None = None):
    """Read the effective policy. The ONLY I/O in this module.

    The walk-up starts from THIS file, not from jobcore's: jobcore cannot know
    who imported it, and starting from its own location only works by luck —
    true under an editable install, false under a normal ``pip install``,
    where the walk finds nothing and the server silently runs on defaults.
    """
    return jobcore_config.current(Path(__file__), env=env)


def bind(*, env: Mapping[str, str] | None = None) -> Bound:
    """One snapshot + the engine it implies + this server's settings."""
    loaded = snapshot(env=env)
    return Bound(
        loaded=loaded,
        engine=engine_for(loaded),
        settings=loaded.server(SERVER),
    )


def _defaults() -> Bound:
    """Today's literals, with no file read and no environment consulted.

    This is what every ``bound=None`` call site gets, so a caller that has not
    been migrated behaves exactly as it did before this module existed.
    """
    loaded = jobcore_config.Loaded(
        policy=DEFAULT_POLICY,
        source=None,
        revision=0,
        policy_rev=0,
        policy_hash=DEFAULT_POLICY.policy_hash,
        content_hash=None,
        provenance={},
        searched=(),
        config_error=None,
    )
    return Bound(
        loaded=loaded,
        engine=engine_for(loaded),
        settings=DEFAULT_POLICY.server(SERVER),
    )


DEFAULTS: Bound = _defaults()


def resolve(bound: Bound | None) -> Bound:
    """``bound`` or the shipped defaults. Never reads a file."""
    return DEFAULTS if bound is None else bound


# ── The candidate block, layered over data/profile.json ────────────────────
#
# `data/profile.json` predates the shared document and is still the thing a
# human opens to see what their scores are computed against. The shared
# `candidate` block is the central mechanism. Both exist, so precedence has to
# be stated rather than discovered:
#
#   a field CONFIGURED IN THE FILE wins; every other field comes from the
#   local profile.
#
# Provenance, not emptiness, decides "configured" — see Bound.configured.
# With no config file present nothing is configured, so the effective profile
# is the local one, unchanged, field for field.

#: shared ``candidate.*`` key -> local ``Profile`` field.
FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("candidate.name", "name"),
    ("candidate.headline", "headline"),
    ("candidate.years_experience", "years_experience"),
    ("candidate.skills", "skills"),
    ("candidate.titles", "titles"),
    ("candidate.notice_period_days", "notice_period_days"),
    ("candidate.avoid_companies", "avoid_companies"),
)

#: The pay keys, kept out of FIELD_MAP because they are denominated and the
#: local profile spells them differently.
PAY_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("candidate.pay.%s.floor" % PAY_UNIT, "min_pay_usd_year"),
    ("candidate.pay.%s.expected" % PAY_UNIT, "expected_pay_usd_year"),
)


def states_nothing(value: Any) -> bool:
    """True for a file value that NAMES a key without answering it.

    ``null`` and an empty list/string are what a generated template writes for
    a field nobody has filled in. Zero is NOT one of them, and that distinction
    is the whole point: ``notice_period_days: 0`` is a real answer, which is why
    :meth:`Bound.configured` keys on provenance rather than truthiness.
    """
    if value is None:
        return True
    return isinstance(value, (list, tuple, set, dict, str)) and len(value) == 0


def effective_profile(local, bound: Bound | None = None):
    """(profile, provenance) — the local profile with configured fields applied.

    *local* is never mutated; a pydantic copy is returned. ``provenance`` maps
    each field name to ``"config"`` or ``"local"`` so a tool can say which
    number produced a score instead of leaving the reader to guess.

    **AN EMPTY CONFIGURED VALUE NEVER OVERRIDES A LOCAL ONE.** Provenance alone
    is not enough here, and this is measured rather than argued: the documented
    way to start using the shared config is to copy ``jobhunt.example.json``,
    which - like ``jobcore.config.default_document()`` - writes the WHOLE
    candidate block out at its defaults. Every key in it is then provenance
    ``"file"``, so ``skills: []`` and ``pay.floor: null`` replaced a local
    profile carrying 88 skills and a real floor. MEASURED on 2026-08-22: three
    representative scores went 100 -> 30, 88 -> 23, 80 -> 20, every "Strong
    match" became "Weak match", and BOTH config fingerprints were unchanged
    throughout - ``policy_hash`` covers the values, not which of them arrived
    from the file, so nothing downstream could have detected it.

    The asymmetry decides it. Reading "empty" as "unset" costs him the ability
    to CLEAR a local list from the shared file - he clears it with
    ``uplers_set_profile()`` instead, and :meth:`Bound.notes` says when the file
    named a key it did not answer. Reading it as "set to nothing" silently
    destroys every score on the server. Those are not comparable harms.
    """
    bound = resolve(bound)
    candidate = bound.candidate
    updates: dict[str, Any] = {}
    where: dict[str, str] = {}

    for key, attr in FIELD_MAP:
        if not bound.configured(key):
            where[attr] = "local"
            continue
        value = getattr(candidate, key.rsplit(".", 1)[1])
        if isinstance(value, tuple):
            value = list(value)
        if states_nothing(value):
            where[attr] = "local"
            continue
        updates[attr] = value
        where[attr] = "config"

    band = bound.pay_band()
    for key, attr in PAY_FIELD_MAP:
        if not bound.configured(key):
            where[attr] = "local"
            continue
        value = getattr(band, key.rsplit(".", 1)[1])
        if states_nothing(value):
            where[attr] = "local"
            continue
        updates[attr] = value
        where[attr] = "config"

    # `location` is one string locally and a LIST in the shared block, because
    # naukri scores against several. The engine already reads
    # candidate.locations directly; the single string stays the local
    # display/scoring value, and the first configured location wins when one
    # is set, so the two never disagree on the row the reader sees.
    if bound.configured("candidate.locations") and candidate.locations:
        updates["location"] = candidate.locations[0]
        where["location"] = "config"
    else:
        where["location"] = "local"

    if not updates:
        return (local, where)
    return (local.model_copy(update=updates), where)


def expected_pay(profile) -> float | None:
    """The figure the +5 salary bonus is scored against, in USD/year.

    Two decisions, and they are not the same one: ``expected`` is the bonus
    target, ``floor`` is walk-away. Before the split there was one number
    doing both jobs, so the default is the floor — which is exactly what this
    server passed as ``profile_expected_ctc`` before, byte for byte.
    """
    explicit = getattr(profile, "expected_pay_usd_year", None)
    return explicit if explicit is not None else profile.min_pay_usd_year
