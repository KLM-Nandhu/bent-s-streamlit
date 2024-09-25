import streamlit as st
import openai
from typing import List, Dict
import asyncio
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

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

# Initialize YouTube API client
@st.cache_data(show_spinner=False)
def get_youtube_client():
    return build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

youtube = get_youtube_client()

# Fetch video information using YouTube API
@st.cache_data(show_spinner=False)
def get_video_info(video_id: str) -> Dict:
    try:
        response = youtube.videos().list(
            part='snippet,statistics,contentDetails',
            id=video_id
        ).execute()

        video_data = response['items'][0]
        return {
            'id': video_id,
            'title': video_data['snippet']['title'],
            'description': video_data['snippet']['description'],
            'thumbnail_url': video_data['snippet']['thumbnails']['high']['url'],
            'view_count': video_data['statistics']['viewCount'],
            'like_count': video_data['statistics']['likeCount'],
            'duration': video_data['contentDetails']['duration'],
            'published_at': video_data['snippet']['publishedAt']
        }
    except Exception as e:
        return f"An error occurred while fetching video info: {str(e)}"

# Fetch YouTube comments for a video
@st.cache_data(show_spinner=False)
def get_all_comments(video_id: str) -> List[Dict]:
    try:
        comments = []
        nextPageToken = None
        while True:
            response = youtube.commentThreads().list(
                part='snippet',
                videoId=video_id,
                maxResults=100,
                pageToken=nextPageToken,
                order='time'
            ).execute()

            for item in response['items']:
                comment = item['snippet']['topLevelComment']['snippet']
                comments.append({
                    'author': comment['authorDisplayName'],
                    'text': comment['textDisplay'],
                    'likes': comment['likeCount'],
                    'published_at': comment['publishedAt']
                })

            nextPageToken = response.get('nextPageToken')
            if not nextPageToken:
                break

        return comments
    except Exception as e:
        return f"An error occurred while fetching comments: {str(e)}"

# Fetch transcript from YouTube using multiple methods asynchronously
async def get_video_transcript_with_timestamps(video_id: str) -> List[Dict]:
    methods = [
        fetch_transcript_directly,
        fetch_transcript_with_rotating_proxy,
        fetch_transcript_with_selenium,
        fetch_transcript_from_third_party,
        fetch_transcript_with_custom_headers
    ]
    
    random.shuffle(methods)  # Randomize the order of methods
    
    for method in methods:
        try:
            transcript = method(video_id)
            if transcript:
                return transcript
        except Exception as e:
            print(f"Method {method.__name__} failed: {str(e)}")
        time.sleep(random.uniform(1, 3))  # Add random delay between attempts
    
    return f"An error occurred while fetching the transcript: All methods failed"

# Method 1: Fetch transcript directly using YouTubeTranscript API
def fetch_transcript_directly(video_id: str) -> List[Dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
    return YouTubeTranscriptApi.get_transcript(video_id)

# Method 2: Fetch transcript using rotating proxies
def fetch_transcript_with_rotating_proxy(video_id: str) -> List[Dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
    proxy_api_url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
    response = requests.get(proxy_api_url)
    proxies = response.text.strip().split('\r\n')
    
    for proxy in proxies:
        try:
            proxy_dict = {
                'http': f'http://{proxy}',
                'https': f'http://{proxy}',
            }
            return YouTubeTranscriptApi.get_transcript(video_id, proxies=proxy_dict)
        except Exception as e:
            print(f"Proxy {proxy} failed: {str(e)}")
    
    raise Exception("All proxies failed")

# Method 3: Fetch transcript using Selenium for web scraping
def fetch_transcript_with_selenium(video_id: str) -> List[Dict]:
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(f"https://www.youtube.com/watch?v={video_id}")
        
        # Wait for and click the "Show Transcript" button
        transcript_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-label='Show transcript']"))
        )
        transcript_button.click()
        
        # Wait for the transcript to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[id='segments-container']"))
        )
        
        # Extract transcript
        transcript_elements = driver.find_elements(By.CSS_SELECTOR, "div[id='segments-container'] div.segment")
        transcript = []
        for element in transcript_elements:
            time_element = element.find_element(By.CSS_SELECTOR, "div.segment-timestamp")
            text_element = element.find_element(By.CSS_SELECTOR, "div.segment-text")
            transcript.append({
                "text": text_element.text,
                "start": time_element.text,
                "duration": 0  # Duration is not provided in this method
            })
        
        return transcript
    finally:
        driver.quit()

# Asynchronous processing of the transcript chunks to generate a structured transcript
async def process_transcript_chunk(chunk: str, video_id: str) -> str:
    prompt = f"""This is a portion of a video transcript. Please organize this content into the following structure:
    Product name (if applicable):
    Starting timestamp:
    Ending Timestamp:
    Transcript:
    
    Here's the transcript chunk:
    {chunk}
    """
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that organizes video transcripts without altering their content."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while processing with GPT-4: {str(e)}"

# Process the full transcript and combine processed chunks
async def process_full_transcript(transcript: List[Dict], video_id: str) -> str:
    chunk_size = 10000  # Adjust this value based on your needs
    full_transcript = " ".join([f"{format_time(entry['start'])}: {entry['text']}" for entry in transcript])
    chunks = [full_transcript[i:i+chunk_size] for i in range(0, len(full_transcript), chunk_size)]
    
    processed_chunks = []
    for chunk in chunks:
        processed_chunk = await process_transcript_chunk(chunk, video_id)
        processed_chunks.append(processed_chunk)
    
    return "\n\n".join(processed_chunks)

# Generate the final blog post from processed transcript and video information
async def generate_blog_post(processed_transcript: str, video_info: Dict) -> str:
    prompt = f"""Based on the following processed transcript and video information, create a comprehensive blog post. The blog post should include:
    1. Title
    2. Introduction
    3. Main content with subheadings (including timestamps)
    4. Key moments
    5. Conclusion
    6. Product links (if any mentioned in the video)
    7. Affiliate information (if provided)
    8. Equipment used (if mentioned)

    Video Title: {video_info['title']}
    Video Description: {video_info['description']}
    
    Processed Transcript:
    {processed_transcript}
    """
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates detailed blog posts from video transcripts and information."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while generating the blog post: {str(e)}"

# Utility to format time from seconds
def format_time(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

# Frontend UI Layout using modern CSS for Streamlit
st.set_page_config(layout="wide")
st.markdown("""
<style>
    body {
        color: #333;
        font-family: 'Roboto', sans-serif;
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
        font-size: 18px;
        border-radius: 5px;
        cursor: pointer;
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
    }
    .comments-scrollable {
        max-height: 500px;
        overflow-y: auto;
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

# Main Application Logic and Layout
st.title("BENT-S-BLOG")

video_id = st.text_input("Enter YouTube Video ID")

if st.button("Process Transcript and Generate Blog Post"):
    if video_id:
        with st.spinner("Processing transcript and generating blog post..."):
            video_info = get_video_info(video_id)
            if isinstance(video_info, dict):
                transcript = asyncio.run(get_video_transcript_with_timestamps(video_id))
                comments = get_all_comments(video_id)
                if isinstance(transcript, list) and isinstance(comments, list):
                    processed_transcript = asyncio.run(process_full_transcript(transcript, video_id))
                    blog_post = asyncio.run(generate_blog_post(processed_transcript, video_info))
                    formatted_blog_post = blog_post
                    
                    # Display the blog post
                    st.markdown("<div class='blog-post'>", unsafe_allow_html=True)
                    st.markdown("<div class='blog-content'>", unsafe_allow_html=True)
                    st.markdown(formatted_blog_post, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                    
                    # Display comments in a scrollable container
                    st.markdown("<div class='comments-container'>", unsafe_allow_html=True)
                    st.markdown("<h2>Comments</h2>", unsafe_allow_html=True)
                    st.markdown("<div class='comments-scrollable'>", unsafe_allow_html=True)
                    for comment in comments:
                        st.markdown(f"""
                            <div class="comment">
                                <div class="comment-author">{comment['author']}</div>
                                <div class="comment-date">{comment['published_at']}</div>
                                <div class="comment-text">{comment['text']}</div>
                                <div class="comment-likes">👍 {comment['likes']}</div>
                            </div>
                        """, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.error(transcript if isinstance(transcript, str) else comments)
            else:
                st.error(video_info)
    else:
         st.error("Please enter a YouTube Video ID.")
