# Use Python 3.14 as per project standards
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies for Postgres and general tools. `upgrade` pulls the
# Debian security fixes published after the base image was built.
RUN apt-get update && apt-get -y upgrade && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    zlib1g-dev \
    postgresql-client \
    netcat-openbsd \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies from requirements.txt, then remove pip: nothing
# in the running stack calls it (Composer unpacks inline releases itself), and
# its vendored packages are what image scanners flag. `python -m ensurepip`
# brings it back in a derived image that needs it.
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m pip uninstall --yes pip

# Surface the baked DjangoLux version as an image label so an external updater
# (composer's preflight version gate) can refuse to recreate onto an image
# older than the deployment's active runtime version. Passed at build time
# (CI derives it from the pinned requirement); empty locally = gate skipped.
ARG DLUX_BAKED_VERSION=""
LABEL org.dlux_crm.dlux_baked_version="${DLUX_BAKED_VERSION}"

# Optional schema-1 project release metadata consumed by Composer and surfaced
# in DjangoLux's application-image update review.
ARG DLUX_PROJECT_RELEASE_MANIFEST=""
LABEL org.dlux.project.release-manifest="${DLUX_PROJECT_RELEASE_MANIFEST}"

# The stack contract schema this Dockerfile was written for.
LABEL org.dlux.stack-schema="5"

# Copy the project files
COPY . /app/

# Create every mount point the app containers use, group 0 and group-writable.
# A named volume Docker creates on the first start copies its mount point's mode,
# so an image that runs as uid 10001 (group 0) can write to `static` and the
# runtime volume from that start on. Root ignores the group bits.
RUN mkdir -p /app/imports /app/logs /app/media /app/staticfiles /opt/dlux-runtime \
    && chgrp 0 /app/imports /app/logs /app/media /app/staticfiles /opt/dlux-runtime \
    && chmod g+rwX /app/imports /app/logs /app/media /app/staticfiles /opt/dlux-runtime

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Entrypoint script handles migrations/waiting
ENTRYPOINT ["/app/entrypoint.sh"]
