# Codespace image. Pinned by digest like every other image in the repository; bump the
# digest in a pull request (the tag is shown for readability only).
FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm@sha256:68aef3859e340a2b0cc63260978c5d40e82f48e30fb00503c59cea9104ff8a6b

# The base image ships a Yarn apt source whose signing key is not installed, so every
# `apt-get update` fails and takes the docker-in-docker feature install down with it.
# Nothing here uses Yarn.
RUN rm -f /etc/apt/sources.list.d/yarn*.list \
    && ! grep -rqs dl.yarnpkg.com /etc/apt/sources.list /etc/apt/sources.list.d/

USER vscode
