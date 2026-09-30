"""AWS Lambda entrypoint.

Deployed handler: ``app.lambda_handler``.

The S3, CSV, and Braze steps live in their own modules so they can be called
without this handler. See ``AGENTS.md``.
"""

if __package__:
    from .handler import lambda_handler
else:
    from handler import lambda_handler

__all__ = ["lambda_handler"]
