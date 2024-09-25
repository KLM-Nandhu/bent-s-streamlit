import streamlit as st
import openai
from typing import List, Dict
import asyncio
import aiohttp
import requests
from io import BytesIO
from datetime import datetime
import base64
from googleapiclient.discovery import build
import re
import random
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from functools import lru_cache

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# Implement caching for expensive operations
@lru_cache(maxsize=100)
def get_video_info(video_id: str) -> Dict:
    # Existing implementation
    pass

@lru_cache(maxsize=100)
def get_video_transcript_with_timestamps(video_id: str) -> List[Dict]:
    # Existing implementation
    pass

# Implement asynchronous fetching for comments
async def get_comments_page(session, video_id: str, page_token: str = None) -> Tuple[List[Dict], str]:
    try:
        url = f"https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={video_id}&key={YOUTUBE_API_KEY}&maxResults=100&order=time"
        if page_token:
            url += f"&pageToken={page_token}"
        
        async with session.get(url) as response:
            data = await response.json()
            
        comments = [
            {
                'author': item['snippet']['topLevelComment']['snippet']['authorDisplayName'],
                'text': item['snippet']['topLevelComment']['snippet']['textDisplay'],
                'likes': item['snippet']['topLevelComment']['snippet']['likeCount'],
                'published_at': item['snippet']['topLevelComment']['snippet']['publishedAt']
            }
            for item in data['items']
        ]

        next_page_token = data.get('nextPageToken')
        return comments, next_page_token

    except Exception as e:
        return f"An error occurred while fetching comments: {str(e)}", None

async def get_all_comments(video_id: str) -> List[Dict]:
    async with aiohttp.ClientSession() as session:
        all_comments = []
        next_page_token = None
        
        while True:
            comments, next_page_token = await get_comments_page(session, video_id, next_page_token)
            if isinstance(comments, list):
                all_comments.extend(comments)
            
            if not next_page_token:
                break
        
        return all_comments

# Optimize transcript processing
def chunk_transcript(transcript: List[Dict], chunk_size: int = 1000) -> List[str]:
    full_text = " ".join(f"{format_time(entry['start'])}: {entry['text']}" for entry in transcript)
    return [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]

async def process_transcript_chunk(chunk: str) -> str:
    prompt = f"Summarize this transcript chunk: {chunk}"
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",  # Use a faster model for initial processing
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes video transcripts."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150  # Limit the response size
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while processing with GPT-3.5-turbo: {str(e)}"

async def process_full_transcript(transcript: List[Dict]) -> str:
    chunks = chunk_transcript(transcript)
    summaries = await asyncio.gather(*[process_transcript_chunk(chunk) for chunk in chunks])
    return " ".join(summaries)

# Main processing function
async def process_video(video_id: str):
    video_info = get_video_info(video_id)
    transcript = get_video_transcript_with_timestamps(video_id)
    
    # Run these tasks concurrently
    comments_task = asyncio.create_task(get_all_comments(video_id))
    transcript_task = asyncio.create_task(process_full_transcript(transcript))
    
    comments = await comments_task
    processed_transcript = await transcript_task
    
    blog_post = await generate_blog_post(processed_transcript, video_info)
    formatted_blog_post = format_blog_post(blog_post, video_info)
    
    return video_info, formatted_blog_post, comments

# Streamlit UI
st.set_page_config(layout="wide")
