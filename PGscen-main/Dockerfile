# Dockerfile to reproduce the GitHub Actions test job locally
FROM mambaorg/micromamba:1.5.10-bullseye

ENV MAMBA_CACHE_DIR=/tmp/mamba
# Activate the created environment for subsequent RUN instructions
ARG MAMBA_DOCKERFILE_ACTIVATE=1

WORKDIR /workspace

# Create the Conda environment defined in the repository
COPY environment.yml /tmp/environment.yml
RUN micromamba env create -f /tmp/environment.yml && \
    micromamba clean --all --yes
ENV MAMBA_DEFAULT_ENV=pgscen

# Copy the project into a temporary, writable build directory to avoid chown
# issues when source files are owned by the host. We'll install from the
# temp dir, then run tests using the environment.
COPY . /workspace

# Create a writable build workspace in /tmp and make it writable to everyone
# (avoid chown which is not supported on some macOS-mounted filesystems).
RUN mkdir -p /tmp/buildworkspace /tmp/mamba && \
    cp -a /workspace/. /tmp/buildworkspace && \
    chmod -R a+w /tmp/buildworkspace /tmp/mamba || true

# Use /tmp as HOME and /tmp/mamba for mamba cache to avoid lockfile/dotfile
# permission issues. Run pip install from the temp buildworkspace as root so
# wheel building and build/ directories can be created freely.
ENV HOME=/tmp
ENV MAMBA_CACHE_DIR=/tmp/mamba
RUN bash -lc "TMPDIR=/tmp micromamba run -n pgscen python -m pip install /tmp/buildworkspace"

# If Rsafd.zip is present in the workspace, unzip and install it into the
# R environment so rpy2.imports.importr('Rsafd') works at runtime.
RUN bash -lc "if [ -f /tmp/buildworkspace/Rsafd.zip ]; then \
        TMPDIR=/tmp MAMBA_CACHE_DIR=/tmp/mamba HOME=/tmp micromamba run -n pgscen python -m zipfile -e /tmp/buildworkspace/Rsafd.zip /tmp && \
        TMPDIR=/tmp MAMBA_CACHE_DIR=/tmp/mamba HOME=/tmp micromamba run -n pgscen Rscript -e \"install.packages('/tmp/Rsafd', repos=NULL, type='source')\"; \
    else \
        echo 'Rsafd.zip not found in build workspace; skipping Rsafd install'; \
    fi"

# Run the same test harness inside the container (as root) using the same
# cache/home settings to avoid cross-user lockfile issues.
CMD ["bash", "-c", "MAMBA_CACHE_DIR=/tmp/mamba HOME=/tmp micromamba run -n pgscen bash test/test_run.sh"]
