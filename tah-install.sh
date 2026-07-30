tmp="$(mktemp -d)" && \
curl -fL "https://tah.iota.macrocosmos.ai/download/token/release-iota-signup" -o "$tmp/iota.dmg" && \
mkdir "$tmp/mnt" && \
hdiutil attach "$tmp/iota.dmg" -nobrowse -readonly -mountpoint "$tmp/mnt" >/dev/null && \
app="$(find "$tmp/mnt" -maxdepth 1 -name '*.app' -print -quit)" && \
test -n "$app" && \
sudo ditto "$app" "/Applications/$(basename "$app")"; \
status=$?; hdiutil detach "$tmp/mnt" -quiet 2>/dev/null; rm -rf "$tmp"; exit "$status"