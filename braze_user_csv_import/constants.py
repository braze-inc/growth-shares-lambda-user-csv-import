"""Limits shared by the CSV import and the Braze /users/track client."""

# Stop with this much runtime still left so a follow-up Lambda can be started.
# 600_000 ms is 10 minutes. Lambda's max timeout is 15 minutes (900_000 ms).
FUNCTION_RUN_TIME = 10 * 60 * 1_000
FUNCTION_TIME_OUT = 900_000 - FUNCTION_RUN_TIME

# Concurrent /users/track requests in one wave.
MAX_THREADS = 20

# Attempts per request, including the first call. 429 and 5xx are retried.
MAX_RETRIES = 5

# Current /users/track limit: 75 objects combined across attributes, events,
# and purchases. This importer sends attributes only, so 75 users per request.
BRAZE_BATCH_SIZE = 75

# S3 and local files are read in 10 MB chunks.
CHUNK_SIZE = 1024 * 1024 * 10
