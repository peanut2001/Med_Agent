"""Bound multipart bodies before the framework spools uploaded files."""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class UploadBodyLimitMiddleware:
    def __init__(self, app, limits: dict[str, int]):
        self.app = app
        self.limits = limits

    async def __call__(self, scope, receive, send):
        limit = self.limits.get(scope.get("path"))
        if scope["type"] != "http" or scope.get("method") != "POST" or limit is None:
            return await self.app(scope, receive, send)

        rejected = JSONResponse(status_code=413, content={"detail": "Upload exceeds the request size limit"})
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})(scope, receive, send)
        if declared > limit:
            return await rejected(scope, receive, send)

        received = 0
        exceeded = False

        async def limited_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    # The multipart parser closes its temporary files when
                    # this exception occurs. Convert its 400 response to 413.
                    raise MultiPartException("Upload exceeds the request size limit")
            return message

        async def guarded_send(message):
            if not exceeded:
                await send(message)

        await self.app(scope, limited_receive, guarded_send)
        if exceeded:
            await rejected(scope, receive, send)
