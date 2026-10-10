#!/bin/bash

OPAL_VERSION=4.0.4
OPAL_PACK_REVISION=1
BUNDLE_VERSION=${OPAL_VERSION}-${OPAL_PACK_REVISION}

# build the Opal Presenter dependency file - remember to update requirements.txt if needed. Certain devel packages might be needed.
# first get the flatpak-pip-generator tool if not already present
if [ ! -f "flatpak-pip-generator" ]; then
  curl -O https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator
fi
python flatpak-pip-generator  --requirements-file  requirements.txt

# Finally do the build, install for the user and into a repo in the repo-folder
mkdir repo
flatpak-builder --install-deps-from=flathub --user --install --force-clean --repo=repo opalpresenter-flatpak-builddir net.tbcproductions.OpalPresenter.yml

# create flatpak bundle file
echo "Bundle into a flatpak file, this can take a while..."
flatpak build-bundle repo OpalPresenter-${BUNDLE_VERSION}.flatpak net.tbcproductions.OpalPresenter
