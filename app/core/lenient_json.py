import json

from starlette.requests import Request


async def _lenient_json(self: Request) -> object:
    """Starlette's default Request.json() rejects raw control characters (e.g. literal newlines)
    inside JSON string values per strict JSON, even though Python's own json module supports
    accepting them. Callers routinely paste multi-line text (job descriptions, resume text) straight
    into a JSON field without escaping newlines — reject that and every such request 422s on a syntax
    technicality before our own validation ever runs. strict=False accepts it instead."""
    if not hasattr(self, "_json"):
        body = await self.body()
        self._json = json.loads(body, strict=False)
    return self._json


Request.json = _lenient_json
