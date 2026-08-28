import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def embed_text(text: str, max_retries: int = 5) -> list[float]:
    """Get a 3072-dim embedding vector for a piece of text, with retry on rate limits."""
    for attempt in range(max_retries):
        try:
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text
            )
            return result.embeddings[0].values
        except errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = 2 ** attempt * 5  # 5s, 10s, 20s, 40s, 80s
                print(f"Rate limited. Waiting {wait_time}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait_time)
            else:
                raise
    raise RuntimeError("Max retries exceeded for embedding call")


# How many chunks go up in one embed_content call. The API accepts a list of
# contents and returns one embedding per item, so a 100-page PDF (~600 chunks)
# costs a handful of round trips instead of 600. Sequential single-chunk calls
# were the bottleneck, not the embedding itself.
#
# Measured against a free-tier key, the ceiling here is quota, not batch size:
# identical 100-item batches alternately succeed and return 429 depending on
# what the per-minute window has already absorbed. So the batch size is a
# starting point, not a guarantee -- embed_texts() halves it on repeated 429
# rather than failing, which is what keeps a large ingest alive on a throttled
# key. See MIN_EMBED_BATCH_SIZE.
EMBED_BATCH_SIZE = 100

# Below this, splitting further buys nothing -- a batch of 1 that still 429s is
# a quota problem no amount of subdivision fixes, so let the retry/backoff in
# embed_text() handle it and surface the failure if even that gives up.
MIN_EMBED_BATCH_SIZE = 8


def embed_texts(texts: list[str], max_retries: int = 5) -> list[list[float]]:
    """Embed many chunks, batched. Returns one vector per input, in order.

    Two different failures are handled differently, because they mean opposite
    things:

      * a non-rate-limit error means the request itself is bad, and retrying it
        unchanged will fail identically -- so the batch degrades to one call
        per chunk, costing the bad chunk rather than its 99 neighbours;
      * a 429 means the request was fine and the quota was not, so it backs off
        and retries, then halves the batch and tries again. Failing a whole
        100-page ingest because a minute-long window was busy is the wrong
        outcome when waiting and sending less would have worked.
    """
    vectors: list[list[float]] = []

    def embed_batch(batch: list[str], batch_size: int) -> list[list[float]]:
        for attempt in range(max_retries):
            try:
                result = client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=batch,
                )
                return [e.values for e in result.embeddings]
            except errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait_time = 2 ** attempt * 5  # 5s, 10s, 20s, 40s, 80s
                    print(f"Rate limited on a batch of {len(batch)}. Waiting "
                          f"{wait_time}s before retry {attempt+1}/{max_retries}...")
                    time.sleep(wait_time)
                else:
                    return [embed_text(t, max_retries=max_retries) for t in batch]

        # Backoff exhausted. Send less per request rather than give up.
        if batch_size > MIN_EMBED_BATCH_SIZE:
            smaller = max(MIN_EMBED_BATCH_SIZE, batch_size // 2)
            print(f"Still rate limited; splitting batch of {len(batch)} "
                  f"into chunks of {smaller}.")
            out: list[list[float]] = []
            for i in range(0, len(batch), smaller):
                out.extend(embed_batch(batch[i:i + smaller], smaller))
            return out

        # At the floor, fall back to the single-item path, which has its own
        # independent backoff and raises if that is exhausted too.
        return [embed_text(t, max_retries=max_retries) for t in batch]

    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        vectors.extend(
            embed_batch(texts[start:start + EMBED_BATCH_SIZE], EMBED_BATCH_SIZE)
        )

    return vectors