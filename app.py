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
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
    
    body {
        color: #333;
        font-family: 'Roboto', sans-serif;
        line-height: 1.6;
        background-color: #f0f2f5;
    }
    .main {
        max-width: 800px;
        margin: 0 auto;
        background-color: white;
        padding: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        border-radius: 8px;
    }
    .stButton>button {
        width: 100%;
        background-color: #4CAF50;
        color: white;
        border: none;
        padding: 12px 20px;
        text-align: center;
        text-decoration: none;
        display: inline-block;
        font-size: 18px;
        margin: 4px 2px;
        cursor: pointer;
        border-radius: 5px;
        transition: background-color 0.3s;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    .blog-post {
        margin-top: 2rem;
    }
    .blog-post h1 {
        font-size: 2.8em;
        color: #2c3e50;
        margin-bottom: 0.5em;
        border-bottom: 2px solid #3498db;
        padding-bottom: 10px;
        font-weight: 700;
    }
    .blog-post h2 {
        font-size: 2.2em;
        color: #34495e;
        margin-top: 1.2em;
        margin-bottom: 0.5em;
        font-weight: 700;
        border-left: 4px solid #3498db;
        padding-left: 10px;
    }
    .blog-post h3 {
        font-size: 1.8em;
        color: #34495e;
        margin-top: 1em;
        margin-bottom: 0.5em;
        font-weight: 600;
    }
    .blog-post p {
        margin-bottom: 1em;
        text-align: justify;
        font-size: 1.1em;
        line-height: 1.8;
    }
    .blog-meta {
        font-size: 0.9em;
        color: #7f8c8d;
        margin-bottom: 1em;
    }
    .blog-content {
        background-color: #fff;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .blog-image {
        max-width: 100%;
        height: auto;
        margin: 1em 0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .comments-container {
        max-width: 800px;
        margin: 2rem auto;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 20px;
        background-color: #f9f9f9;
    }
    .comments-scrollable {
        max-height: 500px;
        overflow-y: auto;
    }
    .comment {
        background-color: #ffffff;
        border-left: 4px solid #3498db;
        padding: 15px;
        margin-bottom: 15px;
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    .comment-author {
        font-weight: bold;
        color: #2c3e50;
    }
    .comment-date {
        font-size: 0.8em;
        color: #7f8c8d;
    }
    .comment-text {
        margin-top: 5px;
    }
    .comment-likes {
        font-size: 0.9em;
        color: #3498db;
        margin-top: 5px;
    }
    a {
        color: #3498db;
        text-decoration: none;
    }
    a:hover {
        text-decoration: underline;
    }
</style>
""", unsafe_allow_html=True)

st.title("BENT-S-BLOG")

video_id = st.text_input("Enter YouTube Video ID")

if st.button("Click To Generate"):
    if video_id:
        start_time = time.time()
        with st.spinner("Processing video..."):
            video_info, formatted_blog_post, comments = asyncio.run(process_video(video_id))
            
            # Display the content
            st.markdown("<div class='content-container'>", unsafe_allow_html=True)
            
            st.markdown("<div class='blog-post'>", unsafe_allow_html=True)
            st.markdown(formatted_blog_post, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='comments-container'>", unsafe_allow_html=True)
            st.markdown("<h2>Comments</h2>", unsafe_allow_html=True)
            st.markdown("<div class='comments-scrollable'>", unsafe_allow_html=True)
            for comment in comments[:100]:  # Limit to first 100 comments for performance
                st.markdown(f"""
                <div class="comment">
                    <div class="comment-author">{comment['author']}</div>
                    <div class="comment-date">{comment['published_at']}</div>
                    <div class="comment-text">{comment['text']}</div>
                    <div class="comment-likes">:+1: {comment['likes']}</div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
            end_time = time.time()
            total_time = end_time - start_time
            st.markdown(f"<div class='total-time'>Total time taken: {total_time:.2f} seconds</div>", unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.error("Please enter a YouTube Video ID.")
