from wtbot.vfs.wikisource import WikisourceVfs

"""VFS service layer.

Layering (top-down):

  wtbot.api.vfs         thin HTTP adapter — params in, status codes out
  wtbot.vfs.wikisource  wikisource:// ProofreadPage overlay (synthetic tree)
  wtbot.vfs.nodes       typed path resolution for the overlay
  wtbot.vfs.paths       WikiPath parsing shared by all layers

A title-addressed mediawiki:// layer (namespace/subpage aware) and a
PageStore beneath the overlay are the next step of this refactor.
"""

__all__ = ["WikisourceVfs"]
