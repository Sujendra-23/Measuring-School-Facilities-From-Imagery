"""
Central place for settings that the rest of the pipeline reads from.

Everything here can be overridden with an environment variable of the same
name (see .env.example), so nobody has to edit source to change an API key
or swap the vision model.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # picks up a local .env file if one exists

# --- Vision model (facility detection) ---
# Primary extraction model, used for all 25 schools. gpt-5.4, not gpt-4o:
# tested head-to-head on the same image, gpt-5.4 answered in ~4s (no slower
# than gpt-4o) at lower per-token cost ($1.25/$7.50 vs $2.50/$10 per 1M),
# and visibly better-calibrated -- it dropped confidence specifically on the
# portables count in a construction-obscured case and said why in its notes,
# instead of defaulting to a flat ~0.8-0.9 regardless of difficulty.
# (gpt-5.5's default reasoning mode burned 6000+ reasoning tokens and ~85s
# on the same single image; gpt-5.5-pro didn't return within 150s at all --
# both are the wrong shape of "powerful" for a repeated batch-classification
# call, whatever their merit on a single hard problem.)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

# Second opinion for validation/second_opinion.py: gpt-4o, the former
# primary model. This doubles as an old-vs-new comparison -- how much the
# gpt-4o -> gpt-5.4 switch actually changed the answers -- on top of its
# validation role. Still same-vendor, not cross-provider; the memo says so.
SECOND_OPINION_MODEL = os.environ.get("SECOND_OPINION_MODEL", "gpt-4o")

# --- Imagery source: USGS NAIP, served through Esri's ArcGIS ImageServer REST API ---
# Public federal aerial imagery, no API key required. Covers the continental US
# at ~0.6m/pixel and re-flies every state every 2-3 years, which is why we also
# pull the acquisition date for every image we fetch.
NAIP_IMAGE_SERVER = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer"

# --- Geolocation refinement: OpenStreetMap Overpass API ---
# Used to check the CCD lat/lon against a real, named school footprint before
# we crop an image around it. No key required.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_SEARCH_RADIUS_M = 2000  # how far from the CCD point we'll look for a matching campus
OSM_NAME_MATCH_THRESHOLD = 0.55  # below this fuzzy-match score, we don't trust the OSM hit

# --- Image crop sizing ---
IMAGE_PIXELS = 1024  # square output, both dimensions
# Crop size used when we have no campus polygon to size against (osm_school_point
# or ccd_raw). Was 350m; raised after finding a real miss (Coleman HS) where a
# confirmed point still fell short of the campus's actual track/fields/courts,
# which sat just outside the old box. This is a blunt fix, not a precise one --
# a proper one would query nearby athletic/leisure features and size the crop
# to them, but that needs another Overpass round-trip, and Overpass has been
# too unreliable this session to add a second dependency on it. Bounded risk:
# this only affects the schools that already carry the lowest location
# confidence, and the prompt already tells the model to be more conservative
# about edge-of-frame objects on an unconfirmed boundary.
DEFAULT_CROP_METERS = 500
CROP_BUFFER_FRACTION = 0.25  # extra margin added around a known campus polygon

# --- Paths ---
DATA_CSV = "data/schools_sample.csv"
OUTPUT_DIR = "output"
IMAGE_CACHE_DIR = "output/images"
MEASUREMENTS_CSV = "output/measurements.csv"

# --- Politeness / rate limits ---
# Overpass's public instance will reject bursty traffic; a small fixed delay
# keeps us well under that without adding retry/backoff machinery for it.
OVERPASS_DELAY_SECONDS = 1.0
# OpenAI hasn't shown rate-limit trouble for this key at this volume;
# vision_extract.py still backs off properly (honoring Retry-After) if a
# 429 does show up, so this is just politeness, not load-bearing.
OPENAI_DELAY_SECONDS = 1.0

# --- Elevation: USGS 3DEP, same Esri ImageServer REST pattern as NAIP above ---
# Bare-earth DEM, free and keyless. exportImage can return a float32 GeoTIFF
# (pixelType=F32) of elevation in meters, which Pillow reads as mode "F".
DEM_IMAGE_SERVER = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
DEM_RESOLUTION_M = 10  # target pixel size; 3DEP serves 1/3 arc-second (~10m) nationwide
# Per-request tile edge in pixels. Deliberately small: a default 500m campus is
# only ~50 px at 10m, so 32 px tiles split it 2x2 and the mosaic step is
# actually exercised on every campus, not just on unusually large ones.
DEM_MAX_TILE_PIXELS = 32
TERRAIN_CSV = "output/terrain.csv"
