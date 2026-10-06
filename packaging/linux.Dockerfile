# Builds the Linux app on any Docker host (incl. Apple Silicon via emulation):
#   docker build --platform linux/amd64 -f packaging/linux.Dockerfile --output dist-linux .
# Ubuntu 22.04 (glibc 2.35) so the result runs on 22.04+, Debian 12+ and similar.
FROM ubuntu:22.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
# vlc: only for the smoke test below (the app uses the target machine's VLC).
# libxcb-*/libxkbcommon-x11: so PyInstaller bundles what Qt's xcb plugin needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils ca-certificates libvlc5 vlc-plugin-base \
        libegl1 libgl1 libfontconfig1 libdbus-1-3 libxkbcommon-x11-0 \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /src
COPY requirements.txt .
RUN uv venv --python 3.12 /venv && uv pip install --python /venv -r requirements.txt pyinstaller
COPY . .
RUN /venv/bin/pyinstaller --noconfirm --clean videosync.spec \
    && ! ls dist/videosync/_internal/libvlc* 2>/dev/null \
    # Smoke test: the dialog blocks, so surviving 5 s (exit 124) means imports and Qt start fine.
    && (QT_QPA_PLATFORM=offscreen timeout 5 dist/videosync/videosync; test $? -eq 124) \
    && tar -C dist -czf /videosync-linux-x86_64.tar.gz videosync

FROM scratch
COPY --from=build /videosync-linux-x86_64.tar.gz /
