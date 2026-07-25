from typing import Any


class SafeLocator:
    """Wraps a Playwright Locator exposing only what's needed to fill a field. Deliberately has no
    click(), press(), dispatch_event(), or evaluate() — the only ways to trigger a form submission —
    so no filler built on top of this can submit anything, regardless of what selector it targets."""

    def __init__(self, locator: Any):
        self._locator = locator

    async def fill(self, value: str) -> None:
        await self._locator.fill(value)

    async def set_input_files(self, files: Any) -> None:
        await self._locator.set_input_files(files)

    async def count(self) -> int:
        return await self._locator.count()

    async def is_visible(self) -> bool:
        return await self._locator.is_visible()

    @property
    def first(self) -> "SafeLocator":
        return SafeLocator(self._locator.first)


class SafeFormPage:
    """Wraps a Playwright Page for the autofill feature. Structurally forbids submitting the form:
    click(), press(), dispatch_event(), and evaluate() are not exposed anywhere on this class or on
    SafeLocator, so code that only ever holds a SafeFormPage/SafeLocator — which is all filler code
    receives, never the raw Page — has no way to trigger a submit/apply action. This is enforced by
    the absence of the capability, not by convention or a check that could be forgotten."""

    def __init__(self, page: Any):
        self._page = page

    async def goto(self, url: str, **kwargs: Any) -> None:
        await self._page.goto(url, **kwargs)

    def get_by_label(self, text: str, **kwargs: Any) -> SafeLocator:
        return SafeLocator(self._page.get_by_label(text, **kwargs))

    def locator(self, selector: str) -> SafeLocator:
        return SafeLocator(self._page.locator(selector))

    async def screenshot(self, **kwargs: Any) -> bytes:
        return await self._page.screenshot(**kwargs)
