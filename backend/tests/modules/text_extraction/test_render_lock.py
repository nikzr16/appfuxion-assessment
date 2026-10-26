"""pypdfium2 is not thread-safe: rendering is serialised by ``_RENDER_LOCK`` (PRD 0005 D12)."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.modules.text_extraction import service
from tests.modules.text_extraction import samples


def test_the_lock_is_held_while_pages_are_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[bool] = []
    real = service._prepare_image

    def probe(source: Any) -> bytes:
        held.append(service._RENDER_LOCK.locked())
        return real(source)

    monkeypatch.setattr(service, "_prepare_image", probe)

    images = service._render_pages(samples.scanned_pdf(pages=2), max_pages=2)

    assert len(images) == 2
    assert held == [True, True]
    assert not service._RENDER_LOCK.locked()


def test_concurrent_renders_all_succeed() -> None:
    data = samples.scanned_pdf(pages=2)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service._render_pages(data, max_pages=2), range(8)))

    assert all(len(images) == 2 for images in results)
    assert len({images[0] for images in results}) == 1  # identical, uncorrupted output
