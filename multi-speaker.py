from TTS.api import TTS

# 初始化多说话人英文模型（VCTK数据集）
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
# tts -h
# tts --list_models
# tts --model_name "tts_models/multilingual/multi-dataset/xtts_v2" --list_speaker_idxs
# speakers = [
#     'Claribel Dervla',  # 女
#     'Daisy Studious',  # 女
#     'Gracie Wise',  # 女
#     'Tammie Ema',  # 女
#     'Alison Dietlinde',  # 女
#     'Ana Florence',  # 女
#     'Annmarie Nele',  # 女
#     'Asya Anara',  # 女
#     'Brenda Stern',  # 女
#     'Gitta Nikolina',  # 女
#     'Henriette Usha',  # 女
#     'Sofia Hellen',  # 女
#     'Tammy Grit',  # 女
#     'Tanja Adelina',  # 女
#     'Vjollca Johnnie',  # 女
#     'Andrew Chipper',  # 男
#     'Badr Odhiambo',  # 男
#     'Dionisio Schuyler',  # 男
#     'Royston Min',  # 男
#     'Viktor Eka',  # 男
#     'Abrahan Mack',  # 男
#     'Adde Michal',  # 男
#     'Baldur Sanjin',  # 男
#     'Craig Gutsy',  # 男
#     'Damien Black',  # 男
#     'Gilberto Mathias',  # 男
#     'Ilkin Urbano',  # 男
#     'Kazuhiko Atallah',  # 男
#     'Ludvig Milivoj',  # 男
#     'Suad Qasim',  # 男
#     'Torcull Diarmuid',  # 男
#     'Viktor Menelaos',  # 男
#     'Zacharie Aimilios',  # 男
#     'Nova Hogarth',  # 女
#     'Maja Ruoho',  # 女
#     'Uta Obando',  # 女
#     'Lidiya Szekeres',  # 女
#     'Chandra MacFarland',  # 女
#     'Szofi Granger',  # 女
#     'Camilla Holmström',  # 女
#     'Lilya Stainthorpe',  # 女
#     'Zofija Kendrick',  # 女
#     'Narelle Moon',  # 女
#     'Barbora MacLean',  # 女
#     'Alexandra Hisakawa',  # 女
#     'Alma María',  # 女
#     'Rosemary Okafor',  # 女
#     'Ige Behringer',  # 女
#     'Filip Traverse',  # 男
#     'Damjan Chapman',  # 男
#     'Wulf Carlevaro',  # 男
#     'Aaron Dreschner',  # 男
#     'Kumar Dahl',  # 男
#     'Eugenio Mataracı',  # 男
#     'Ferran Simen',  # 男
#     'Xavier Hayasaka',  # 男
#     'Luis Moray',  # 男
#     'Marcos Rudaski'  # 男
# ]
# tts --model_name "tts_models/multilingual/multi-dataset/xtts_v2" --list_language_idxs
# ['en', 'es', 'fr', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'ar', 'zh-cn', 'hu', 'ko', 'ja', 'hi']

# 循环生成不同说话人语音
for speaker in ['Tammie Ema', 'Damjan Chapman']:
    # 中文语音生成
    tts.tts_to_file(
        text="你好，生成不同说话人语音",
        file_path=f"multi-{speaker.replace(' ', '-')}-zh.wav",
        speaker=speaker,
        language='zh-cn'
    )
    
    # 英文语音生成
    tts.tts_to_file(
        text="Hello, generate different speaker voices",
        file_path=f"multi-{speaker.replace(' ', '-')}-en.wav",
        speaker=speaker,
        language='en'
    )