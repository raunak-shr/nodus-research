/** Which history this browser reads.
 *
 *  Nodus has no accounts, and one deployment can be read by several people. The
 *  server scopes a history to an owner key, and this is where that key comes
 *  from: a random token minted once per browser and kept in local storage, sent
 *  on every handshake. Queries are stamped with it, listings filter on it, and
 *  anything reached through a query id is refused to anyone else.
 *
 *  Two honest limits, both of them consequences of having no accounts:
 *
 *  - **It is a bearer token, not a login.** Whoever holds it reads that history.
 *    There is nothing to sign in to and nothing to revoke.
 *  - **Clearing site data mints a new one.** The old runs are still on the
 *    server; they are simply no longer reachable from this browser. Invisible,
 *    not deleted — which is why `describeOwner` says so rather than implying
 *    the history is gone.
 *
 *  Kept out of `ws.ts` because it is storage, not transport: the socket is
 *  handed a token and never has to know where it came from.
 */

const STORAGE_KEY = 'nodus.owner'

/** Matches the server's accepted shape — see `app/services/ownership.py`. A
 *  token the server rejects would silently fall back to an address bucket
 *  shared with everything else on this address, so the client mints one that
 *  cannot be rejected rather than trusting whatever is in storage. */
const VALID = /^[A-Za-z0-9_-]{8,96}$/

function mint(): string {
  const random = globalThis.crypto?.randomUUID?.()
  if (random) return `b-${random.replace(/-/g, '')}`
  // Old browsers and non-secure contexts have no randomUUID. Two draws of
  // Math.random are weak, but the alternative is no token at all, which shares
  // this browser's history with every other client on the same address.
  return `b-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`
}

/** This browser's owner token, minted on first use. */
export function ownerToken(): string {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored && VALID.test(stored)) return stored
    const minted = mint()
    window.localStorage.setItem(STORAGE_KEY, minted)
    return minted
  } catch {
    // Private modes and blocked storage throw on access. A per-session token is
    // still better than none: the history holds for as long as the tab lives.
    sessionToken ??= mint()
    return sessionToken
  }
}

let sessionToken: string | null = null

/** How the sidebar explains the scope, given what the server echoed back.
 *
 *  `t:` means the token arrived and this history is this browser's. `a:` means
 *  it did not, and the server fell back to the connection's address — which is
 *  shared with anything else on it, so that is worth saying out loud rather
 *  than leaving a reader to assume isolation they do not have.
 */
export function describeOwner(owner: string | null): string | null {
  if (!owner) return null
  if (owner.startsWith('t:')) return 'History is scoped to this browser'
  return 'History is scoped to this network address — no owner token reached the server'
}
