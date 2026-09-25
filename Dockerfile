# Serve-only image for the MapBiomas Venezuela viewer.
#
# What this image is NOT: it cannot rebuild the data. Every tool under tools/ that
# produces data imports `from osgeo import gdal`, which needs the GDAL Python
# bindings, and rasterio's wheels do not provide those. Regeneration therefore runs
# where GDAL is installed, normally the developer's machine, and the result is
# synced to the server. This image serves what already exists.
#
# Why it is small: rasterio's manylinux wheels bundle their own GDAL, so no system
# GDAL packages are installed. Only numpy, rasterio and fastapi/uvicorn are runtime
# imports; the COG extent for /api/meta is parsed from the BigTIFF header by hand.
#
# The data is NOT copied in. data/raw, data/cog and data/tiles are gitignored and
# total about 13 GB, so baking them into an image would be absurd. They are mounted
# at /app/data/... instead, and only the two big subdirectories are mounted so that
# the small tracked metadata copied below is not shadowed.

FROM python:3.13-slim

# libexpat1 is required at RUNTIME, not at build time, and this is the difference
# between an image that builds and an image that works: rasterio's manylinux wheel
# bundles GDAL but still links dynamically against libexpat, and python:3.13-slim
# does not ship it. Without this the map, the legend and the composition panel all
# serve normally, and the clip endpoint alone fails with
# "libexpat.so.1: cannot open shared object file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MAPBIOMAS_REPO_ROOT=/app \
    MAPBIOMAS_COUNTRY=venezuela \
    MAPBIOMAS_COLLECTION=3

WORKDIR /app

# Dependencies first, so the layer is reused while the code changes.
COPY viewer/requirements.txt /app/viewer/requirements.txt
RUN pip install --no-cache-dir -r /app/viewer/requirements.txt

# Application code and the tracked metadata the service reads at import: the
# codebook for the legend and the composition outputs and manifests for /api/meta
# and for the composition panel.
COPY tools/ /app/tools/
COPY viewer/ /app/viewer/
COPY data/legend/ /app/data/legend/
COPY data/derived/ /app/data/derived/

EXPOSE 8000

# The service refuses to start if the manifest or the codebook is missing or
# malformed, so a mis-mounted volume fails loudly at boot instead of degrading.
CMD ["uvicorn", "tools.serve_viewer:app", "--host", "0.0.0.0", "--port", "8000"]
