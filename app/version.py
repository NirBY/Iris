"""Build version: injected via IRIS_VERSION at image build time, "dev" locally."""

import os

VERSION = os.environ.get("IRIS_VERSION", "dev")
