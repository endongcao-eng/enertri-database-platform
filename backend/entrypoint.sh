#!/usr/bin/env sh
set -eu
# V4.2 deliberately performs no migrations, seeding or task recovery here.
# Those operations belong to the one-shot `init` service / scripts/bootstrap.py.
exec "$@"
