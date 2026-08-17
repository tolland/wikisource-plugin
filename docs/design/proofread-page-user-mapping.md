# ProofreadPage user mapping during promotion

## The field is content, not an account key

A ProofreadPage body serializes its quality state inside wikitext:

```xml
<pagequality level="3" user="Tolland" />
```

The `user` attribute is not referentially linked to a MediaWiki account. XML
imports can preserve a username that does not exist on the destination wiki,
and raw content does not say whether a name was written locally, copied from
another site, or imported with history. A name that happens to exist on both
sites does not settle that provenance either.

ProofreadPage's interactive editor normally preserves the old user while the
quality level is unchanged and records the current editor when the level
changes. The promotion path writes serialized content through the API, so it
must choose explicitly how cross-site account names are handled.

## MVP policy: map only configured credentials

The first implementation uses the one cross-site account correspondence the
application already knows: each site's `SiteCredential.username`.

For a promotion from source site A to target site B:

1. An absent or empty `pagequality user` is left absent or empty.
2. A user other than A's configured credential username is left unchanged.
3. A user equal to A's configured credential username is replaced by B's
   configured credential username.
4. When both configured usernames are the same, the original body is left
   byte-for-byte unchanged.

The mapping is directional at use time but symmetric in effect: reversing the
promotion reverses which site's credential is the source and which is the
target. It does not inspect whether an arbitrary username exists remotely and
does not infer identity from equal spelling.

This policy is intentionally conservative. It prevents a local automation
account such as `Admin` from leaking into a public wiki when the public writing
account is `Tolland`, while preserving imported, empty, and otherwise unknown
attribution rather than replacing it speculatively.

## Known ambiguity

The MVP cannot distinguish these bodies by their text alone:

- a local user genuinely set `user="Admin"`;
- a remote `Admin` attribution was copied locally;
- an XML import preserved `user="Admin"`;
- raw wikitext set the attribute manually.

Promotion and `RevisionLink(origin=copy)` provide provenance for revisions
created through this application, but historical and externally imported
revisions can remain unknown. The MVP accepts that ambiguity and changes only
the configured source credential name.

## Escalation path

Add more schema only when the MVP produces a concrete failure:

1. **Explicit account correspondence.** Sparse `SiteAccount` rows keyed by
   `(site_pk, username)` and unordered `AccountLink` rows can map arbitrary
   identities between sites. Unknown users should still remain unchanged.
2. **Parsed content metadata.** `ProofreadPageContentMeta`, sharing its primary
   key with `Content`, can cache the literal quality level, user, and tag
   presence. These are deterministic properties of the serialized content.
3. **Per-slot provenance.** `ProofreadPageSlotMeta`, sharing the composite
   `(revision_pk, role)` key with `Slot`, can record whether the attribution is
   local, copied, imported, inherited, or unknown, plus the originating/source
   revision. Provenance cannot live on `Content`, because identical content is
   deduplicated across revisions and sites that may have acquired it by
   different routes.

The account-link and slot-provenance models solve different problems. Account
links express that two site-local names identify the same operator; slot
metadata explains how a particular serialized attribution reached a revision.
