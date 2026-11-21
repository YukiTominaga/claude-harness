#!/bin/bash
exec bash "$(dirname "$0")/../_fixtures/setup.sh" tracker full decoy-cascading-deletes decoy-move-check-in-sql decoy-completed-at-case
