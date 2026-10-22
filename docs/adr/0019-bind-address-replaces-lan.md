# ADR-0019: `--bind <ip>` replaces `--lan`; second-device access goes over a tunnel or a VPN address

**Status:** Accepted, 2026-10-22 (proposed and implemented the same day; the owner accepted the
eight pass-3 records together at 16:36 BST) · **Date:** 2026-10-22 · **Deciders:** council pass 3
of the 2026-10-21 full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6,
deepseek-r1, mistral-large-3), arbitrated by argument by the review coordinator under the owner's
standing delegation; accepted by Andy Taylor (owner). · **Change:** 2026-10-22 council pass 3, ruling D7 (**3–2**; dissent recorded below);
implemented in `db30f9ca`, merge `c10c5096` (lane E, `web-bootstrap-token`).

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7`.

## Context

`studyloop web --lan` bound every interface (`0.0.0.0`) and protected the dashboard with HTTP
Basic authentication; the 2026-10-21 review's lane 3 confirmed that `--lan` already **generates
and prints a password** when none is given and pinned that with a test, and the setup guide
carried a five-bullet warning. The dashboard carries the agent terminal, a shell-equivalent
WebSocket, and the learner's session content.

Every seat agreed on the fact: RFC 7617 Basic credentials must not cross a network without TLS,
and on a cleartext link Basic protects nothing against anyone who can see the traffic. The
pass-1 council had split 2–3 on severity and ruled TLS out of scope for an autonomous lane. What
remained was a product decision: the second-device case is real for this product's audience (a
tablet beside the laptop, an accessibility workflow), and `0.0.0.0` exposes the dashboard on every
network the machine ever joins, which is the accidental-exposure class worth removing.

Also verified: `cli/_web.py` already had `_candidate_lan_hosts()`, which enumerates the machine's
addresses, so validating a chosen address against the interfaces cost nothing new.

## Decision

`--bind <ip>` replaces `--lan`; `--lan` stays one release as a deprecated alias.

- **`--bind <ip>`** serves exactly one address. `_validated_bind_address` refuses (exit 2) a value
  that is not an IP literal, a **wildcard** (`0.0.0.0`/`::`, which is the every-interface
  exposure the ruling removes), or an address no interface of this machine carries, and names the
  candidates it can find plus "any VPN address, e.g. `tailscale ip -4`". `--lan` and `--bind`
  cannot be combined.
- **`--lan`** maps to the every-interface bind for one release, prints a deprecation line and the
  existing five caveats, and is removed in the next release.
- **Password behaviour is unchanged and stays pinned**: `--lan`, and `--bind` with any
  non-loopback address, never serve without a password; when none is given one is generated. The
  docs **stop calling Basic a second factor**: it is a password gate on an already-private link,
  not encryption.
- The **recommended second-device path** in `docs/setup-guide.md` is, in order: an `ssh -L` tunnel
  to loopback (nothing listens beyond the Mac); a Tailscale or other VPN address with
  `--bind "$(tailscale ip -4)"` (the tunnel encrypts; the same-origin WebSocket needs nothing
  extra on either machine); and last the deprecated `--lan`.
- The launcher function (`session/orchestrator.py`) accepts a bind address, passes it to the
  child as `--bind` and opens the browser on that address with the sign-in token of ADR-0014.
  The `studyloop study` command does **not yet expose** it (see Consequences); today `--bind` is
  reached through `studyloop web` directly.

Grounding adopted: RFC 7617 on Basic over cleartext; secure by default (no wildcard bind without
saying so); the accessibility argument for keeping a supported second-device path.

## Alternatives considered

- **(a) Keep `--lan` with the documented caveat and the fail-closed password.** Rejected by every
  seat: it keeps the wildcard bind as the one documented way to reach a second device.
- **(c) Built-in TLS with a self-signed certificate or `mkcert`.** Rejected as naive by every
  seat: certificate trust on the second device, renewal, and a false sense of a solved problem;
  the tunnel path gives real encryption with no certificate handling in StudyLoop.
- **(d) Remove `--lan` outright; second-device access only via the user's own tunnel.** The
  minority position (gpt-6-astra, deepseek-r1). Their argument: Basic is not a second factor and
  the product should not offer a cleartext mode at all. The majority (kimi-k3, grok-4.6,
  mistral-large-3) and the coordinator: (d) deletes a real accessibility workflow, while (b)
  removes the accidental-exposure class and makes the recommended path one where the traffic is
  encrypted. Astra's objection is accepted in the documentation (Basic is not a second factor).
  mistral's own dissent ("a tunnel still exposes Basic to users on the same host") is a category
  error: same-host exposure is the subject of ADR-0014, not of this decision.

**Reversal path recorded for the owner:** choosing (d) after the fact is cheaper than the reverse,
because it is deleting the `--bind` option and its tests, not adding them. Nothing in ADR-0014
depends on `--bind` existing.

## Consequences

- A learner who typed `--lan` gets a deprecation line and the same behaviour for one release; a
  learner who types `--bind 0.0.0.0` is refused and told why.
- **Not yet wired** (ledgered in the review record): `studyloop study --bind` (`cli/_study.py`
  and `session/start.py` still take only `--lan`); `session/start.py` prints the LAN address
  without the sign-in token; `runtime_feedback.py` still suggests `--lan`; eight docs pages
  mention `--lan` without `--bind`.
- **The `practice_check` hop dials `127.0.0.1`** (`modules/hop.py`). A server bound to a tailnet
  address *alone* does not listen there, so `studyloop drill` cannot reach it. The lane
  recommends also listening on loopback; that is an **owner decision** recorded in the ledger,
  not taken here.

*Amendment, 2026-10-22 (plan 4, lane K, merged `affbd076`; coordinator unit `7c7dc813`): both
items above are closed. `studyloop study --bind` is wired and validated before tmux starts; the
printed address carries the sign-in token; `runtime_feedback.py` and every docs page say `--bind`;
a non-loopback `--bind` also listens on `127.0.0.1` (coordinator decision, item 3), so the hop
reaches the server. Doing that exposed a second blocker the brief had not seen: under any password
mode the Basic auth middleware answered the hop with 401 before the route's own loopback+token guard
could run, so `drill` had never worked under `--lan` either. The middleware now passes exactly one
request shape through, a POST to the practice-check route carrying its capability header; the
route's guard is stronger than the password for that path. `studyloop web --show-url` re-prints
the sign-in address (item 4). The `--lan` alias is deprecated in the changelog and removed next
release, as decided.*
- The setup guide's second-device section is now tunnel-first; a learner following it needs
  `ssh` or Tailscale on the second device, which is the cost the minority weighed.

## Verification

`packages/studyloop/tests/test_web_bind.py`: `--bind` with an address this machine lacks exits 2
and prints candidates; a wildcard is refused with the `--lan` pointer; `--bind <present address>`
binds there (asserted on the uvicorn config host); a non-loopback bind never serves without a
password and `--lan` without one still generates one; `--lan` emits the deprecation line and the
five caveats; `--lan`/`--bind` together are refused; the launcher passes `--bind` through and opens
the browser there (IPv6 bracketed). `test_lan_auth.py`: the Basic gate itself (401 without
credentials on `/`, `/session`, `/api` and static assets; the WebSocket closes 1008). Coordinator
probe against a real server on the lane tree: foreign `Host` 400 unchanged; the printed sign-in URL
names the bound address.
