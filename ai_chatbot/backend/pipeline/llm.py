"""
llm.py -- one place that calls Gemini, so retry behaviour is uniform.

The flash models return transient 503s under load and 429s on the free tier's
20-requests/day cap. Every caller in this codebase makes several model calls
per user turn, which multiplies the chance of hitting one, so retrying with
backoff belongs here rather than in each caller.

What a caller does when retries are exhausted is NOT uniform, and must not be:
see invigilator.guard_check (fails closed -- an unverifiable answer is refused)
versus escalation.self_check (fails open -- an unreachable grader should not
manufacture support tickets). Those are deliberate opposites.
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

ATTEMPTS = 3
BACKOFF_SECONDS = 1.5


class ModelUnavailable(Exception):
    """Gemini could not be reached after retrying."""


# Incremented every time a call gives up. Callers that swallow
# ModelUnavailable to fail open or closed (guard_check, self_check) hide the
# outage from anything above them, which is right for serving a request and
# wrong for measuring one: the evaluation harness reads this counter to tell
# "the guard judged this unsafe" apart from "the guard never ran". Process
# local and monotonic -- snapshot it, do work, compare.
UNAVAILABLE_COUNT = 0


def generate(prompt: str, config: dict | None = None, model: str | None = None) -> str:
    global UNAVAILABLE_COUNT
    last_error = None
    for attempt in range(ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=model or MODEL, contents=prompt, config=config
            )
            return response.text or ""
        except (genai_errors.ServerError, genai_errors.ClientError) as exc:
            # 5xx and 429 are worth another try; a malformed request never is.
            status = getattr(exc, "code", None)
            if status is not None and status < 500 and status != 429:
                raise
            last_error = exc
            if attempt < ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
    UNAVAILABLE_COUNT += 1
    raise ModelUnavailable(str(last_error))
