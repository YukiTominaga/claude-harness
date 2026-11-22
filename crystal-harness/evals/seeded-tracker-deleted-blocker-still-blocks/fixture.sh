#!/bin/bash
exec bash "$(dirname "$0")/../_fixtures/setup.sh" tracker thin deleted-blocker-still-blocks
