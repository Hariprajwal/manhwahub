import os
import subprocess
from fastapi import FastAPI, HTTPException, Request
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
import importlib.util
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
BASE_DIR = Path(__file__).resolve().parent
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
        system_prompt = f"""You are a Manhwa expert. 
Provide EXACTLY 5 highly relevant manhwa recommendations for {current_year}.
STRICT RULES:
1. Title MUST be the official short name (Max 5 words).
2. Description MUST be a single concise sentence (Max 15 words).
3. Provide the response STRICTLY as a JSON array of objects with "title" and "description".
Example: [{{"title": "Solo Leveling", "description": "The world's weakest hunter becomes the strongest monarch."}}]"""
        
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=os.getenv("MODEL_NAME", "llama3.1-8b"),
        )
        content = response.choices[0].message.content
        import re
        import json
        import ast
        
        # Robust extraction: find the first '[' and last ']'
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            blob = match.group(0)
            try:
                # Try standard JSON first
                recs = json.loads(blob)
                return {"recommendations": recs}
            except json.JSONDecodeError:
                try:
                    # AI might use single quotes, try literal_eval
                    recs = ast.literal_eval(blob)
                    if isinstance(recs, list):
                        return {"recommendations": recs}
                except:
                    pass
        
        return {"recommendations": [{"title": "Error Parsing AI Response", "description": "The AI provided a non-standard response. Try a simpler prompt or refresh the page."}]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_ai_normalization(user_input: str):
    """Uses the provided prompt to get a Master Keyword Array of titles."""
    prompt = f"""You are a manga/manhwa title normalization engine.

Return the best possible official title and 2-3 alternative search variants.

Rules:

* Fix spelling mistakes
* Expand abbreviations
* Provide variations (with and without punctuation)
* If unknown, return NOT_FOUND

Format:
{{
"main": "Official Title",
"alternatives": ["Alt1", "Alt2", "Alt3"]
}}

Examples:
Input: orv
Output:
{{
"main": "Omniscient Reader's Viewpoint",
"alternatives": [
"Omniscient Reader Viewpoint",
"Omniscient Reader",
"ORV"
]
}}

Input: gamer flux
Output:
{{
"main": "NOT_FOUND",
"alternatives": []
}}

Now process:

Input: {user_input}
Output:
"""
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=os.getenv("MODEL_NAME", "llama3.1-8b"),
            temperature=0,
        )
        content = response.choices[0].message.content
        import json
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except:
        pass
    return {"main": user_input, "alternatives": []}

def parse_chapter_info(text: str):
    """
    Extracts chapter or range from text like 'Title 1-20' or 'Title ch 5'.
    Returns (clean_title, ch_from, ch_to)
    """
    import re
    # Match ranges: Name 1-20, Name ch 1-20, Name chapter 1-20
    range_match = re.search(r'(.*?)\s+(?:ch(?:apter)?\s+)?(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if range_match:
        return range_match.group(1).strip(), float(range_match.group(2)), float(range_match.group(3))
    
    # Match single chapter: Name 5, Name ch 5, Name chapter 5
    single_match = re.search(r'(.*?)\s+(?:ch(?:apter)?\s+)?(\d+(?:\.\d+)?)$', text, re.IGNORECASE)
    if single_match:
        return single_match.group(1).strip(), float(single_match.group(2)), float(single_match.group(2))
    
    # Default: No chapter info, target Chapter 1 as requested
    return text.strip(), 1.0, 1.0

@app.get("/download-stream/{slug}")
async def download_stream(request: Request, slug: str):
    async def event_generator():
        try:
            # 1. Parse Chapter Info
            clean_title, ch_from, ch_to = parse_chapter_info(slug)
            yield f"data: INFO: Target Range: Chapter {ch_from} to {ch_to}\n\n"
            
            # 2. Discovery Stage: Try MangaDex first for official aliases
            yield f"data: INFO: [Discovery] Searching MangaDex for official aliases: {clean_title}...\n\n"
            
            # Use SourceFileLoader to handle the uppercase .PY extension safely
            from importlib.machinery import SourceFileLoader
            scraper_path = str(BASE_DIR / "NEW-MANWA.PY")
            try:
                new_manwa = SourceFileLoader("new_manwa", scraper_path).load_module()
            except Exception as loader_err:
                raise ImportError(f"Could not load scraper at {scraper_path}: {loader_err}")
            
            md = new_manwa.MangaDexSource()
            md_results = md.search(clean_title)
            
            master_titles = []
            if md_results:
                best = md_results[0]
                raw_titles = [best["title"]] + best.get("aliases", [])
                yield f"data: INFO: [Discovery] Found on MangaDex. Raw List: {raw_titles}\n\n"
            else:
                yield f"data: WARN: [Discovery] No MangaDex hit. Falling back to AI Normalization...\n\n"
                norm = await get_ai_normalization(clean_title)
                if norm.get("main") == "NOT_FOUND":
                    yield f"data: FAIL: AI Normalization failed. No such manhwa found for '{clean_title}'.\n\n"
                    return
                raw_titles = [norm["main"]] + norm.get("alternatives", [])
                
            # Deduplicate array case-insensitively, keeping punctuation stripped
            seen = set()
            for t in raw_titles:
                t_clean = t.strip()
                t_normalized = t_clean.lower().replace(".", "").replace("!", "").replace(",", "")
                if t_normalized and t_normalized not in seen:
                    seen.add(t_normalized)
                    master_titles.append(t_clean)
            
            yield f"data: INFO: Master List (Deduplicated): {master_titles}\n\n"

            # 3. Trigger Orchestration
            for line in orchestrator.orchestrate_stream(master_titles, ch_range=(ch_from, ch_to)):
                if await request.is_disconnected():
                    print(f"INFO: Client disconnected during download of {slug}. Breaking stream.")
                    break
                yield f"data: {line}\n\n"
                await asyncio.sleep(0.01)
                
            yield f"data: [STREAM_FINISHED]\n\n"
        except (asyncio.CancelledError, ConnectionResetError):
            print(f"INFO: Connection reset or cancelled for {slug}.")
        except Exception as e:
            import traceback
            print(f"ERROR in stream: {e}\n{traceback.format_exc()}")
            yield f"data: ERROR: {str(e)}\n\n"
    
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
