import os
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
from typing import List

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse, StreamingResponse
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
from typing import List
import datetime
import asyncio
from manager import ManhwaOrchestrator

load_dotenv()

app = FastAPI(title="Manhwa Hub API")

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup paths
BASE_DIR = Path(os.getcwd())
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

orchestrator = ManhwaOrchestrator(base_dir=BASE_DIR)

# OpenAI client for Cerebras
client = OpenAI(
    api_key=os.getenv("CEREBRAS_API_KEY"),
    base_url=os.getenv("API_BASE_URL", "https://api.cerebras.ai/v1")
)

# Serves static files for index.html and downloads
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")
app.mount("/panels", StaticFiles(directory=DOWNLOADS_DIR), name="panels")

@app.post("/recommend")
async def recommend_manhwa(prompt: str):
    current_year = datetime.datetime.now().year
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are a Manhwa expert. Recommend 5 CURRENTLY TRENDING manhwas as of {current_year}. Provide each recommendation in this EXACT format:\nTITLE\n-----------\n1-sentence description\n\nSeparate each manhwa recommendation with EXACTLY TWO newlines. DO NOT use bolding or bullet points. Example:\nSolo Leveling\n-----------\nA world-renowned action manhwa about hunters and guilds.\n\nTower of God\n-----------\nA complex fantasy series about a boy searching for a girl in a mysterious tower."},
                {"role": "user", "content": prompt},
            ],
            model=os.getenv("MODEL_NAME", "llama3.1-8b"),
        )
        return {"recommendations": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download-stream/{slug}")
async def download_stream(slug: str):
    def event_generator():
        for line in orchestrator.orchestrate_stream(slug):
            yield f"data: {line}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/list-panels")
async def list_panels():
    """Recursively find all images in the downloads folder."""
    images = []
    for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
        for p in DOWNLOADS_DIR.rglob(ext):
            relative_path = p.relative_to(DOWNLOADS_DIR)
            images.append(str(relative_path).replace("\\", "/"))
    return {"images": sorted(images)}

@app.get("/")
async def root():
    return JSONResponse(content={"message": "Manhwa Hub API is running. Access /static/index.html for the UI."})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
