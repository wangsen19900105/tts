from TTS.api import TTS

# 初始化TTS
tts = TTS("tts_models/en/ljspeech/glow-tts")

# 文本生成语音
text = "Hello, welcome to our TTS tutorial!"
tts.tts_to_file(text=text, file_path="singal-speaker-en.wav")
