# Optional: Use this Dockerfile if you need more customization
# Reference it in devcontainer.json by changing "image" to "build": { "dockerfile": "Dockerfile" }

FROM mcr.microsoft.com/devcontainers/python:3.14

# Install GTK and development dependencies
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    libgtk-4-dev \
    libadwaita-1-dev \
    libcairo2-dev \
    libgirepository1.0-dev \
    libgirepository-2.0-dev \
    gobject-introspection \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    pkg-config \
    python3-dev \
    python3-gi \
    python3-gi-cairo \
    meson \
    ninja-build \
    libx11-dev \
    libxext-dev \
    libxrender-dev \
    libxau-dev \
    libxdmcp-dev \
    x11proto-dev \
    xorg-dev \
    libpango1.0-dev \
    libgdk-pixbuf-2.0-dev \
    libatk1.0-dev \
    dbus-x11 \
    libwayland-dev \
    libwayland-client0 \
    libwayland-cursor0 \
    libwayland-egl1 \
    libxkbcommon-dev \
    libegl1-mesa-dev \
    dconf-service \
    dconf-cli \
    dconf-gsettings-backend \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management for both root and vscode user
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
USER vscode
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
USER root
ENV PATH="/home/vscode/.cargo/bin:/home/vscode/.local/bin:/root/.cargo/bin:/root/.local/bin:${PATH}"

# Install blueprint-compiler from source
RUN cd /tmp \
    && git clone https://gitlab.gnome.org/jwestman/blueprint-compiler.git \
    && cd blueprint-compiler \
    && meson setup build --prefix=/usr \
    && meson install -C build \
    && sed -i '1s|.*|#!/usr/bin/python3|' /usr/bin/blueprint-compiler \
    && cd / \
    && rm -rf /tmp/blueprint-compiler
