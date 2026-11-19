#!/usr/bin/env bash
set -euo pipefail
# Ubuntu gates use this exact archive package, including when the image has
# another ffmpeg. apt authenticates metadata/dependencies; the payload is also
# checked against the committed SHA256 before installation.
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_CODENAME" == noble && "$(dpkg --print-architecture)" == amd64 ]] || exit 78
media_version='7:6.1.1-3ubuntu5'
media_sha256='1a23baace5f2688a47e28119aedae6993cd638e6279a7227dfc52d9a337a1c17'
media_apt="$(mktemp -d)"
trap 'sudo rm -rf "$media_apt"' EXIT
chmod 755 "$media_apt"
mkdir -p "$media_apt/lists/partial"
for suite in noble noble-updates noble-security; do
  printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://archive.ubuntu.com/ubuntu/ %s main universe\n' "$suite"
done > "$media_apt/sources.list"
options=(-o "Dir::Etc::sourcelist=$media_apt/sources.list" -o Dir::Etc::sourceparts=-
  -o "Dir::State::lists=$media_apt/lists" -o Acquire::Retries=3 -o Acquire::http::Timeout=20)
cat "$media_apt/sources.list"
echo "Media validator package: ffmpeg=$media_version SHA256=$media_sha256"
sudo timeout --kill-after=10 180 apt-get "${options[@]}" update --error-on=any
(
  cd "$media_apt"
  sudo timeout --kill-after=10 180 apt-get "${options[@]}" download "ffmpeg=$media_version"
  printf '%s  %s\n' "$media_sha256" ffmpeg_6.1.1-3ubuntu5_amd64.deb | sha256sum --check --strict
)
sudo env DEBIAN_FRONTEND=noninteractive timeout --kill-after=10 180 apt-get "${options[@]}" install \
  --yes --no-install-recommends --reinstall --allow-downgrades "$media_apt/ffmpeg_6.1.1-3ubuntu5_amd64.deb"
[[ "$(dpkg-query -W -f='${Version}' ffmpeg)" == "$media_version" ]]
[[ -z "$(dpkg --verify ffmpeg)" ]]
# A stale PATH shim must not silently replace the verified package executables.
hash -r
[[ "$(command -v ffmpeg)" == /usr/bin/ffmpeg && "$(command -v ffprobe)" == /usr/bin/ffprobe ]]
ffprobe -version
ffmpeg -version
# Exercise the encoder, container and decoder actually required by round 5.
ffmpeg -v error -f lavfi -i color=size=32x32:rate=1 -frames:v 1 -c:v libx264 -pix_fmt yuv420p "$media_apt/smoke.mkv"
ffprobe -v error -show_streams "$media_apt/smoke.mkv"
ffmpeg -v error -i "$media_apt/smoke.mkv" -frames:v 1 "$media_apt/smoke.png"
