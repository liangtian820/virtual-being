"""CLI 语音对话演示（M4）：说→听→回→播。

用法::

    python -m scripts.run_voice_demo --self-test             # edge-tts 生成中文输入后跑全链路（自动化验证）
    python -m scripts.run_voice_demo --input input.mp3       # 用已有中文语音文件
    python -m scripts.run_voice_demo --self-test --play      # 完成后用系统默认播放器打开回复音频

说明：
- 全链路 = ASR（Whisper 本地识别）→ 人格 Agent（Ollama qwen2.5:7b 真实对话）→ TTS（edge-tts 中文女声）。
- 首次识别会加载 Whisper 模型（需联网下载一次，可设 HF_ENDPOINT=https://hf-mirror.com 走镜像）。
- TTS 为微软在线服务，需联网；失败会如实报错，不假装成功。
- 录音功能留待 M5 前端（本脚本支持已有音频文件与自动生成输入两种方式）。
"""
import argparse
import os
import time
from typing import Optional

from app.voice.pipeline import VoicePipeline
from app.voice.tts import EdgeTTS

# --self-test 模式自动生成的中文输入语句
_SELF_TEST_PHRASE = "你好呀，我最近有点累，陪我聊聊天好吗？"


def _generate_input(out_path: str) -> str:
    """用 edge-tts 生成一段中文输入音频（充当"用户说的话"）。"""
    tts = EdgeTTS()
    tts.synthesize(_SELF_TEST_PHRASE, out_path)
    return out_path


def run_chain(input_path: str, session_id: Optional[str], play: bool) -> int:
    """跑一遍 说→听→回→播 全链路并打印延迟基线。"""
    pipeline = VoicePipeline()
    print("=" * 60)
    print("Virtual Being · M4 语音对话（说→听→回→播）")
    print("=" * 60)
    print(f"[输入音频] {input_path}")
    t0 = time.perf_counter()
    result = pipeline.handle_audio(input_path, session_id)
    wall = time.perf_counter() - t0
    print(f"[识别文本] {result['text']}")
    print(f"[TA 回复 ] {result['reply']}")
    lat = result["latencies_ms"]
    print(
        "[延迟基线] ASR {asr}ms | LLM {llm}ms | TTS {tts}ms | 合计 {total}ms"
        "（含模型加载，墙钟 {wall:.1f}s）".format(wall=wall, **lat)
    )
    print(f"[回复音频] {result['audio_path']}")
    print(f"[会话 id ] {result['session_id']}")
    if play and os.name == "nt":
        os.startfile(result["audio_path"])  # type: ignore[attr-defined]
        print("[播放] 已用系统默认播放器打开回复音频")
    return 0


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="Virtual Being M4 语音对话演示")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true", help="自动生成中文输入并跑全链路")
    group.add_argument("--input", metavar="PATH", help="使用已有音频文件作为输入")
    parser.add_argument("--play", action="store_true", help="完成后用系统播放器打开回复音频")
    parser.add_argument("--session-id", default=None, help="沿用指定会话 id（可选）")
    args = parser.parse_args()

    try:
        if args.self_test:
            os.makedirs("data/voice_demo", exist_ok=True)
            input_path = _generate_input("data/voice_demo/input.mp3")
        else:
            input_path = args.input
        run_chain(input_path, args.session_id, args.play)
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n再见～")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
