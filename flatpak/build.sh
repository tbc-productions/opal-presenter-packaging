#!/bin/bash

OPENLP_VERSION=3.9.1
OPENLP_PACK_REVISION=1
BUNDLE_VERSION=${OPENLP_VERSION}-${OPENLP_PACK_REVISION}

# build the OpenLP+ dependency file - remember to update requirements.txt if needed. Certain devel packages might be needed.
# first get the flatpak-pip-generator tool if not already present
if [ ! -f "flatpak-pip-generator" ]; then
  curl -O https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator
fi
python flatpak-pip-generator  --requirements-file  requirements.txt

# Finally do the build, install for the user and into a repo in the repo-folder
mkdir repo
flatpak-builder --install-deps-from=flathub --user --install --force-clean --repo=repo openlpplus-flatpak-builddir org.tbcproductions.OpenLPPlus.yml

# create flatpak bundle file
echo "Bundle into a flatpak file, this can take a while..."
flatpak build-bundle repo OpenLP+-${BUNDLE_VERSION}.flatpak org.tbcproductions.OpenLPPlus
