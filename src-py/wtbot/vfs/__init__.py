from wtbot.vfs.wikisource import WikisourceVfs

"""VFS service layer.

Layering (top-down):

  wtbot.api.vfs         thin HTTP adapter — params in, status codes out
  wtbot.vfs.wikisource  wikisource:// ProofreadPage overlay (synthetic tree)
  wtbot.vfs.nodes       typed path resolution for the overlay
  wtbot.vfs.mediawiki   mediawiki:// title addressing + namespace/subpage rules
  wtbot.vfs.store       PageStore — all SQL (pages, journal, blobs, sites)
  wtbot.vfs.paths       WikiPath parsing shared by all layers

A vanilla mediawiki:// path surface (own router + Kotlin protocol) can be
mounted on the mediawiki layer later without touching the overlay.
"""

__all__ = ["WikisourceVfs"]
