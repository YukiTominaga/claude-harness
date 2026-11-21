#!/bin/bash
exec bash "$(dirname "$0")/../_fixtures/setup.sh" notes-a thin invalid-json-returns-422
