#!/bin/bash
exec bash "$(dirname "$0")/../_fixtures/setup.sh" tracker thin reopen-keeps-completed-at
