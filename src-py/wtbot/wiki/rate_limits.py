import os
from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping

"""How fast we are allowed to talk to a wiki, in one place.

Wikimedia enforces per-identity request budgets at its API gateway
(<https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits>):

    unidentified (no compliant User-Agent)          10 req/min
    unauthenticated, compliant User-Agent          200 req/min
    authenticated, new or few edits                200 req/min
    authenticated, established editor             2000 req/min
    bot flag, or extended global rights             exempt

Nothing reports which bucket a request landed in -- the tiers are enforced
above MediaWiki, and the API does not announce them. So the policy here is
chosen, not discovered, and ``TIER_LIMITS`` exists so the choice can be checked
against the published numbers instead of remembered.

The table is also not the whole policy. The same CDN applies per-IP-block
rules that no document enumerates: traffic from cloud provider ranges is
treated far less generously than the identical request from a residential
connection, and authenticating is the way through. So "unauthenticated gets
the same 200 req/min" is true of the published tiers and misleading as
operational advice -- authenticate for anything that has to keep working.

The defaults target the 200 req/min tier: it is the one an ordinary editing
account gets, 2000 needs an "established editor" standing we cannot ask for,
and exemption needs a bot flag, which is granted for automated editing and is
the wrong thing for an interactive editor to hold.

Two knobs matter and only one of them used to be set. ``read_throttle`` is
pywikibot's ``minthrottle``, the floor between *reads*; ``put_throttle`` is the
floor between *edits*. Fetching a book is essentially all reads, so setting
only the write throttle -- which is what we did -- governed nothing that
mattered while pywikibot's 0.1s read default allowed 600 req/min into a 200
req/min allowance.
"""


class RateLimitTier(str, Enum):
    """The published tiers, named so a policy can say which it targets."""

    unidentified = "unidentified"
    unauthenticated = "unauthenticated"
    authenticated_new = "authenticated_new"
    authenticated_established = "authenticated_established"
    exempt = "exempt"


#: Requests per minute per tier; None means no documented ceiling.
TIER_LIMITS: dict[RateLimitTier, int | None] = {
    RateLimitTier.unidentified: 10,
    RateLimitTier.unauthenticated: 200,
    RateLimitTier.authenticated_new: 200,
    RateLimitTier.authenticated_established: 2000,
    RateLimitTier.exempt: None,
}

#: Wikimedia's own guidance for clients that get a 429/503 with no Retry-After.
DEFAULT_BACKOFF_SECONDS = 5.0

#: Best-practice ceiling on parallel requests from one client, per the same
#: page. We are single-threaded today; this records the limit a future
#: concurrent drain has to respect rather than discover.
MAX_CONCURRENT_REQUESTS = 3

_DEFAULT_USER_AGENT = "wtbot/0.1.0 (https://github.com/tolland/wikisource-plugin)"


@dataclass(frozen=True)
class RateLimitPolicy:
    """The request-pacing half of ``WikiSettings``.

    Grouped rather than left as loose fields because they are only meaningful
    together: a throttle is a rate limit only in combination with what each
    fetch costs, and a retry policy that hides a 429 undoes the throttle
    entirely.
    """

    #: Minimum seconds between reads (pywikibot ``config.minthrottle``).
    #: 0.35s ≈ 170 req/min, inside the 200 tier with room for the requests
    #: pywikibot makes on its own behalf (site detection, siteinfo, paraminfo).
    read_throttle: float = 0.35
    #: Minimum seconds between edits (pywikibot ``config.put_throttle``).
    put_throttle: float = 1.0
    #: Replication lag the wiki may absorb before deferring us
    #: (``config.maxlag``); 5s is MediaWiki's recommendation for bots.
    maxlag: int = 5
    #: Retries for a failed API request. Zero on purpose: every repeated
    #: failure we have actually hit was our bug, and backoff only hid it. A
    #: 429 in particular must not be retried -- it means this policy is too
    #: fast, which is a configuration change, not a runtime workaround.
    max_retries: int = 0
    retry_wait: float = 1.0
    #: Wikimedia's User-Agent policy requires contact information (an email or
    #: a full URL). A non-conforming client is throttled harder -- the
    #: 10 req/min "unidentified" tier -- so this costs request budget when
    #: wrong, quite apart from being impolite.
    user_agent: str = _DEFAULT_USER_AGENT
    #: The tier these numbers are chosen against, for `fits_tier`.
    target_tier: RateLimitTier = RateLimitTier.authenticated_new

    @property
    def reads_per_minute(self) -> float:
        """What ``read_throttle`` permits, ignoring per-request latency (which
        only makes the real rate lower). The number to compare with a tier."""
        if self.read_throttle <= 0:
            return float("inf")
        return 60.0 / self.read_throttle

    def fits_tier(self, tier: RateLimitTier | None = None) -> bool:
        limit = TIER_LIMITS[tier or self.target_tier]
        return limit is None or self.reads_per_minute <= limit

    def slower(self, factor: float = 2.0) -> "RateLimitPolicy":
        """The same policy, pacing reads more slowly. What a 429 calls for --
        offered as a value to configure, not applied automatically, because a
        process that quietly re-paces itself hides the fact that its
        configuration is wrong."""
        return replace(self, read_throttle=self.read_throttle * factor)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RateLimitPolicy":
        e = env if env is not None else os.environ
        default = cls()
        return cls(
            read_throttle=float(
                e.get("WTBOT_WIKI_READ_THROTTLE", default.read_throttle)
            ),
            put_throttle=float(e.get("WTBOT_WIKI_PUT_THROTTLE", default.put_throttle)),
            maxlag=int(e.get("WTBOT_WIKI_MAXLAG", default.maxlag)),
            max_retries=int(e.get("WTBOT_WIKI_MAX_RETRIES", default.max_retries)),
            retry_wait=float(e.get("WTBOT_WIKI_RETRY_WAIT", default.retry_wait)),
            user_agent=e.get("WTBOT_WIKI_USER_AGENT") or default.user_agent,
        )
