
import os
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
print("OpenAI client created successfully")
try:
    response = client.audio.speech.create(
        model="tts-1-hd",
        voice="onyx",
        input="In 1900, three lighthouse keepers vanished. A remote archipelago in Scotland."
    )
    response.stream_to_file(r"C:\Users\openclaw\Desktop\flannan_isles\render_work\openai_tts_demo.mp3")
    print("Synthesis complete: wrote openai_tts_demo.mp3")
    import os as os2
    stat = os2.stat(r"C:\Users\openclaw\Desktop\flannan_isles\render_work\openai_tts_demo.mp3")
    print(f"File size: {stat.st_size:,} bytes ({stat.st_size/1024/1024:.2f} MB)")
except Exception as e:
    print(f"Synthesis error: {e}")
