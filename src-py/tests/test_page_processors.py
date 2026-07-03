from wtbot.page_processors import (
    DefaultProcessor,
    FilePageProcessor,
    IndexAssetProcessor,
    ProofreadIndexProcessor,
    ProofreadPageProcessor,
    processor_for,
)
from wtbot.wiki.wiki_types import RemotePage

"""Processor selection: by content_model first (a Page: is a Page: because it
says proofread-page, wherever the namespace landed), with the File:
namespace as a structural override."""


def _remote(content_model: str, ns_canonical: str | None) -> RemotePage:
    return RemotePage(
        title="T",
        namespace_key=0,
        namespace_canonical=ns_canonical,
        content_model=content_model,
        text="",
    )


def test_file_namespace_overrides_content_model():
    # File: description pages report content_model='wikitext'.
    assert isinstance(processor_for(_remote("wikitext", "File")), FilePageProcessor)


def test_proofread_models_selected_by_content_model_not_namespace():
    assert isinstance(
        processor_for(_remote("proofread-index", "Index")), ProofreadIndexProcessor
    )
    # Namespace unknown/odd — content model still decides.
    assert isinstance(
        processor_for(_remote("proofread-page", "Other")), ProofreadPageProcessor
    )


def test_index_namespace_non_index_content_is_an_asset():
    assert isinstance(
        processor_for(_remote("sanitized-css", "Index")), IndexAssetProcessor
    )


def test_everything_else_is_default():
    assert isinstance(processor_for(_remote("wikitext", None)), DefaultProcessor)
    assert isinstance(processor_for(_remote("wikitext", "")), DefaultProcessor)
