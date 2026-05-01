#!/usr/bin/env bash
# 再生成 (regenerate_audio) 不具合切り分け用ログダンプ。
#
# 使い方:
#   bash scripts/dump_regen_logs.sh                # 直近セッションの末尾 200 行
#   bash scripts/dump_regen_logs.sh --tail 500     # 末尾行数を変える
#   bash scripts/dump_regen_logs.sh --since 5      # 直近 5 分以内のログ
#   bash scripts/dump_regen_logs.sh --filter       # regenerate / TTS / metadata 関連だけ抜粋
#   bash scripts/dump_regen_logs.sh --out dump.txt # ファイルに書き出す (デフォルト: stdout)

set -euo pipefail

TAIL_LINES=200
SINCE_MIN=""
FILTER_ONLY=0
OUT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tail)    TAIL_LINES="$2"; shift 2 ;;
        --since)   SINCE_MIN="$2"; shift 2 ;;
        --filter)  FILTER_ONLY=1; shift ;;
        --out)     OUT_FILE="$2"; shift 2 ;;
        -h|--help)
            grep -E "^# " "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# 出力先 (stdout or file)
if [[ -n "$OUT_FILE" ]]; then
    exec > "$OUT_FILE"
fi

LOG_ROOT="${SAIVERSE_HOME:-$HOME/.saiverse}/user_data/logs"
WAV_DIR="${SAIVERSE_HOME:-$HOME/.saiverse}/user_data/voice/out"
PACK_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "================================================================"
echo " regenerate_audio diagnostic dump"
echo " timestamp     : $(date -Iseconds)"
echo " log root      : $LOG_ROOT"
echo " wav out dir   : $WAV_DIR"
echo " pack dir      : $PACK_DIR"
echo "================================================================"
echo

# ----- 1. 直近セッション特定 -----
if [[ ! -d "$LOG_ROOT" ]]; then
    echo "[ERROR] log root not found: $LOG_ROOT"
    exit 1
fi

# ディレクトリ名 (YYYYMMDD_HHMMSS) でソート、最新を取る
LATEST_SESSION="$(ls -1 "$LOG_ROOT" | sort | tail -n 1)"
if [[ -z "$LATEST_SESSION" ]]; then
    echo "[ERROR] no session directory under $LOG_ROOT"
    exit 1
fi

SESSION_DIR="$LOG_ROOT/$LATEST_SESSION"
BACKEND_LOG="$SESSION_DIR/backend.log"
ERROR_LOG="$SESSION_DIR/error.log"

echo "## latest session : $LATEST_SESSION"
echo "## backend.log    : $BACKEND_LOG"
[[ -f "$BACKEND_LOG" ]] && echo "##   size: $(wc -c < "$BACKEND_LOG") bytes / $(wc -l < "$BACKEND_LOG") lines"
[[ -f "$ERROR_LOG" ]]   && echo "## error.log size : $(wc -c < "$ERROR_LOG") bytes / $(wc -l < "$ERROR_LOG") lines"
echo

# ----- 2. backend.log 抽出 -----
if [[ -f "$BACKEND_LOG" ]]; then
    echo "================================================================"
    echo " backend.log extract"
    if [[ -n "$SINCE_MIN" ]]; then
        echo " (filter: --since ${SINCE_MIN} min)"
    else
        echo " (filter: --tail $TAIL_LINES lines)"
    fi
    echo "================================================================"

    # 元になる行集合を決定
    if [[ -n "$SINCE_MIN" ]]; then
        # ログ先頭が ISO 形式タイムスタンプ前提 (e.g. "2026-05-02 00:12:25,123 ...")
        # SINCE_MIN 分前の境界を計算
        if date -d "$SINCE_MIN minutes ago" +%s >/dev/null 2>&1; then
            CUTOFF_EPOCH="$(date -d "$SINCE_MIN minutes ago" +%s)"
        else
            # macOS/BusyBox 互換 (gnu date 不在)
            CUTOFF_EPOCH=$(($(date +%s) - SINCE_MIN * 60))
        fi
        # ログを舐めて cutoff 以降だけ抜く (パース失敗行は通す)
        awk -v cutoff="$CUTOFF_EPOCH" '
            {
                ts = $1 " " $2;
                gsub(",", ".", ts);
                cmd = "date -d \"" ts "\" +%s 2>/dev/null"
                cmd | getline epoch
                close(cmd)
                if (epoch == "" || epoch + 0 >= cutoff) print $0
            }
        ' "$BACKEND_LOG" > /tmp/.regen_dump_since.$$
        BASE_LINES_FILE="/tmp/.regen_dump_since.$$"
    else
        tail -n "$TAIL_LINES" "$BACKEND_LOG" > /tmp/.regen_dump_tail.$$
        BASE_LINES_FILE="/tmp/.regen_dump_tail.$$"
    fi

    if [[ "$FILTER_ONLY" -eq 1 ]]; then
        # regenerate / TTS / metadata 関連を抜粋
        grep -E "regenerate_audio|enqueue:|TTS first chunk|TTS streamed|TTS wav saved|TTS synthesis failed|notify_stream_ready|notify_audio_ready|set_metadata|emit_addon_event|addon_events:|playback_worker|speak_as_persona|pronunciation_dict applied|No voice profile" \
            "$BASE_LINES_FILE" || echo "(matching lines: 0)"
    else
        cat "$BASE_LINES_FILE"
    fi

    rm -f "$BASE_LINES_FILE"
    echo
else
    echo "[WARN] backend.log not found"
    echo
fi

# ----- 3. error.log があれば末尾 50 行 -----
if [[ -f "$ERROR_LOG" ]] && [[ -s "$ERROR_LOG" ]]; then
    echo "================================================================"
    echo " error.log (tail 50)"
    echo "================================================================"
    tail -n 50 "$ERROR_LOG"
    echo
fi

# ----- 4. voice/out 直近 wav 一覧 -----
echo "================================================================"
echo " voice/out 直近 wav (最新 10 件、新しい順)"
echo "================================================================"
if [[ -d "$WAV_DIR" ]]; then
    ls -lat "$WAV_DIR" 2>/dev/null | head -n 11 | awk 'NR==1 || /\.wav$/'
    echo
    echo "## wav 個数: $(ls -1 "$WAV_DIR"/*.wav 2>/dev/null | wc -l)"
else
    echo "[WARN] $WAV_DIR not found (合成されたことが無い? パスは正しい?)"
fi
echo

# ----- 5. pack 側ファイル mtime (デバッグの取り違え防止) -----
echo "================================================================"
echo " pack files mtime (実装が反映されているかの確認用)"
echo "================================================================"
for f in "$PACK_DIR/api_routes.py" "$PACK_DIR/tools/speak/playback_worker.py" "$PACK_DIR/addon.json"; do
    if [[ -f "$f" ]]; then
        printf '%-60s %s\n' "$(basename "$f" | head)" "$(stat -c '%y' "$f" 2>/dev/null || stat -f '%Sm' "$f")"
    fi
done
echo

echo "================================================================"
echo " end of dump"
echo "================================================================"
