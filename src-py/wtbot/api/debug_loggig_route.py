import json
import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.routing import APIRoute


class DebugLoggingRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            # 1. Read the body bytes safely
            body_bytes = await request.body()

            if body_bytes:
                try:
                    # Try parsing and printing clean JSON
                    body_json = json.loads(body_bytes)
                    logging.debug("\n--- DEBUG REQUEST BODY (JSON) ---")
                    logging.debug(json.dumps(body_json, indent=2))
                except json.JSONDecodeError:
                    # Fallback if it's plain text or binary
                    logging.debug("\n--- DEBUG REQUEST BODY (RAW) ---")
                    logging.debug(body_bytes.decode(errors="ignore"))
            else:
                print("\n--- DEBUG REQUEST BODY: Empty ---")

            # 2. Pass the request to the actual endpoint
            response: Response = await original_route_handler(request)
            return response

        return custom_route_handler
