# Codespace image. Pinned by digest like every other image in the repository; bump the
# digest in a pull request (the tag is shown for readability only).
FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm@sha256:0aa711e570b306c02946cdda67587ce8c65978dbb65691341cbcfd4854dfcfff

# The base image ships a Yarn apt source whose signing key is not installed, so every
# `apt-get update` fails and takes the docker-in-docker feature install down with it.
# Nothing here uses Yarn.
RUN rm -f /etc/apt/sources.list.d/yarn*.list \
    && ! grep -rqs dl.yarnpkg.com /etc/apt/sources.list /etc/apt/sources.list.d/

USER vscode
