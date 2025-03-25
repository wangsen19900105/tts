from TTS.api import TTS

# 初始化TTS
tts = TTS("tts_models/zh-CN/baker/tacotron2-DDC-GST")

# 文本生成语音
text = "爸爸妈妈你好，欢迎来到我的家!"
tts.tts_to_file(text=text, file_path="singal-speaker-zh.wav")