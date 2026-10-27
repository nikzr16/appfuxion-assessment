"""pypdfium2 is not thread-safe: rendering is serialised by ``_RENDER_LOCK`` (PRD 0005 D12)."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.modules.vision import images
from tests.modules.text_extraction import samples


def test_the_lock_is_held_while_pages_are_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[bool] = []
    real = images.prepare_image

    def probe(source: Any, **kwargs: Any) -> images.PageImage:
        held.append(images._RENDER_LOCK.locked())
        return real(source, **kwargs)

    monkeypatch.setattr(images, "prepare_image", probe)

    pages = images.render_pages(samples.scanned_pdf(pages=2), max_pages=2)

    assert len(pages) == 2
    assert held == [True, True]
    assert not images._RENDER_LOCK.locked()


def test_concurrent_renders_all_succeed() -> None:
    data = samples.scanned_pdf(pages=2)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: images.render_pages(data, max_pages=2), range(8)))

    assert all(len(pages) == 2 for pages in results)
    assert len({pages[0].jpeg for pages in results}) == 1  # identical, uncorrupted output
