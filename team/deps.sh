#!/bin/bash
# The free on-Mac engines every update may need: Whisper dictation (whisper.cpp + its model) and the local chat brain (Ollama + qwen2.5:3b).
# Run by update.sh in the background. Each one installs once, only on AC power with room on the disk; a failed download is retried next hour.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
LOCK="$HOME/.config/atticus/deps.lock"; mkdir -p "$(dirname "$LOCK")"
mkdir "$LOCK" 2>/dev/null || exit 0; trap 'rmdir "$LOCK"' EXIT   # one at a time
log() { echo "$(date '+%F %T') deps: $*"; }
pmset -g batt | grep -q "AC Power" || { log "on battery: later"; exit 0; }
free_gb=$(df -g "$HOME" | awk 'NR==2 {print $4}')
[ "${free_gb:-0}" -ge 8 ] || { log "under 8 GB free: skipped"; exit 0; }

# 1. Whisper dictation (more accurate than Apple's; Apple is used until this is ready)
W="$HOME/.local/share/whisper"; MODEL="$W/ggml-large-v3-turbo-q5_0.bin"
if ! command -v whisper-cli >/dev/null || ! command -v whisper-server >/dev/null; then
  if command -v brew >/dev/null; then brew install whisper-cpp >/dev/null 2>&1 && log "whisper.cpp installed" || log "whisper.cpp install failed"
  else log "no Homebrew: Whisper dictation stays on Apple's engine"; fi
fi
if [ ! -s "$MODEL" ]; then
  mkdir -p "$W"
  curl -fsSL --retry 3 -o "$MODEL.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin" \
    && [ "$(stat -f%z "$MODEL.part")" -gt 500000000 ] && mv "$MODEL.part" "$MODEL" && log "Whisper model ready" || { rm -f "$MODEL.part"; log "Whisper model download failed"; }
fi

# 2. Local chat brain: casual talk and questions answered free on this Mac
L="$HOME/.atticus-llm"; O="$L/ollama/ollama"; VER="v0.40.11"; PORT=11435
if [ ! -x "$O" ]; then
  mkdir -p "$L/ollama" && curl -fsSL --retry 3 "https://github.com/ollama/ollama/releases/download/$VER/ollama-darwin.tgz" | tar -xz -C "$L/ollama" \
    && [ -x "$O" ] && log "Ollama $VER installed" || { log "Ollama download failed"; exit 0; }
fi
if [ ! -d "$L/models/manifests/registry.ollama.ai/library/qwen2.5" ]; then
  export OLLAMA_HOST="127.0.0.1:$PORT" OLLAMA_MODELS="$L/models" OLLAMA_NO_CLOUD=1
  started=""; curl -fs "http://$OLLAMA_HOST/api/version" >/dev/null || { "$O" serve >>"$L/serve.log" 2>&1 & started=$!; sleep 3; }
  "$O" pull qwen2.5:3b >/dev/null 2>&1 && log "chat brain ready" || log "chat model download failed"
  [ -n "$started" ] && kill "$started" 2>/dev/null
fi
exit 0
